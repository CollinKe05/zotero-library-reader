#!/usr/bin/env python3
"""Core discovery, snapshot, query, and CLI implementation."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable


PERSONAL_ALIASES = {
    "",
    "1",
    "user",
    "personal",
    "my library",
    "我的文库",
    "个人文库",
    "我的图书馆",
}


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def preference_data_dirs() -> list[Path]:
    roots: list[Path] = []
    home = Path.home()
    if os.name == "nt":
        roots.append(home / "AppData" / "Roaming" / "Zotero" / "Zotero" / "Profiles")
    else:
        roots.extend(
            [
                home / ".zotero" / "zotero",
                home / "Library" / "Application Support" / "Zotero" / "Profiles",
            ]
        )
    results: list[Path] = []
    pattern = re.compile(
        r'user_pref\("extensions\.zotero\.dataDir",\s*"((?:\\.|[^"])*)"\);'
    )
    for root in roots:
        if not root.is_dir():
            continue
        for prefs in root.glob("*/prefs.js"):
            try:
                text = prefs.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            match = pattern.search(text)
            if not match:
                continue
            raw = bytes(match.group(1), "utf-8").decode("unicode_escape")
            results.append(Path(raw).expanduser())
    return results


def locate_data_dirs() -> list[Path]:
    home = Path.home()
    candidates: list[Path] = []
    env_dir = os.environ.get("ZOTERO_DATA_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    candidates.extend(preference_data_dirs())
    candidates.extend([home / "Zotero", home / "Documents" / "Zotero"])
    found: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = os.path.normcase(str(resolved))
        if key in seen:
            continue
        seen.add(key)
        if (resolved / "zotero.sqlite").is_file():
            found.append(resolved)
    return sorted(
        found,
        key=lambda p: (p / "zotero.sqlite").stat().st_mtime,
        reverse=True,
    )


def resolve_data_dir(value: str | None) -> Path:
    if value:
        path = Path(value).expanduser().resolve()
        if path.is_file() and path.name.startswith("zotero.sqlite"):
            path = path.parent
        if not (path / "zotero.sqlite").is_file():
            fail(f"no zotero.sqlite found in {path}")
        return path
    found = locate_data_dirs()
    if not found:
        fail("no Zotero data directory found; pass --data-dir")
    if len(found) > 1:
        choices = ", ".join(str(p) for p in found)
        fail(f"multiple Zotero data directories found; pass --data-dir: {choices}")
    return found[0]


def copy_snapshot(source: Path, destination: Path) -> None:
    sidecars = ["zotero.sqlite-journal", "zotero.sqlite-wal", "zotero.sqlite-shm"]
    last_error: Exception | None = None
    source_db = source / "zotero.sqlite"

    # Prefer SQLite's online backup API when the live database permits a read
    # transaction. This produces a coherent snapshot even while Zotero is open.
    try:
        uri = source_db.resolve().as_uri() + "?mode=ro"
        live = sqlite3.connect(uri, uri=True, timeout=1)
        live.execute("PRAGMA busy_timeout=1000")
        live.execute("SELECT 1").fetchone()
        target = sqlite3.connect(destination / "zotero.sqlite")
        live.backup(target)
        target.close()
        live.close()
        return
    except sqlite3.Error as exc:
        last_error = exc
        try:
            live.close()
        except (NameError, sqlite3.Error):
            pass
        try:
            target.close()
        except (NameError, sqlite3.Error):
            pass

    def state() -> dict[str, tuple[int, int]]:
        result: dict[str, tuple[int, int]] = {}
        for path in [source_db, *(source / name for name in sidecars)]:
            if path.exists():
                stat = path.stat()
                result[path.name] = (stat.st_size, stat.st_mtime_ns)
        return result

    # Fallback for an exclusive rollback-journal lock. Accept a copied file set
    # only when none of its source files changed during the copy.
    for _ in range(5):
        try:
            before = state()
            shutil.copy2(source_db, destination / "zotero.sqlite")
            for name in sidecars:
                src = source / name
                dst = destination / name
                if src.is_file():
                    shutil.copy2(src, dst)
                elif dst.exists():
                    dst.unlink()
            after = state()
            if before != after:
                last_error = RuntimeError("Zotero database changed during snapshot")
                continue
            con = sqlite3.connect(destination / "zotero.sqlite", timeout=5)
            result = con.execute("PRAGMA quick_check").fetchone()[0]
            con.close()
            if result == "ok":
                return
            last_error = RuntimeError(f"SQLite quick_check returned {result}")
        except (OSError, sqlite3.Error) as exc:
            last_error = exc
    fail(
        "could not create a consistent Zotero snapshot"
        + (f": {last_error}" if last_error else "")
        + "; close Zotero and retry"
    )


@contextmanager
def snapshot_connection(data_dir: Path) -> Iterable[sqlite3.Connection]:
    with tempfile.TemporaryDirectory(prefix="zotero-reader-") as temp:
        copy_snapshot(data_dir, Path(temp))
        con = sqlite3.connect(Path(temp) / "zotero.sqlite")
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        try:
            yield con
        finally:
            con.close()


def library_rows(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT l.libraryID, l.type,
               CASE WHEN l.type='user' THEN 'My Library'
                    ELSE COALESCE(g.name, 'Library ' || l.libraryID) END AS name,
               l.editable, l.filesEditable
        FROM libraries l LEFT JOIN groups g ON g.libraryID=l.libraryID
        WHERE COALESCE(l.archived, 0)=0
        ORDER BY l.libraryID
        """
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_library(con: sqlite3.Connection, selector: str | None) -> dict[str, Any]:
    libraries = library_rows(con)
    normalized = (selector or "").strip().casefold()
    if normalized in PERSONAL_ALIASES:
        matches = [row for row in libraries if row["type"] == "user"]
    elif normalized.isdigit():
        matches = [row for row in libraries if row["libraryID"] == int(normalized)]
    else:
        matches = [row for row in libraries if row["name"].casefold() == normalized]
    if len(matches) != 1:
        choices = ", ".join(f'{r["name"]} (ID {r["libraryID"]})' for r in libraries)
        fail(f"library {selector!r} not uniquely found; choices: {choices}")
    return matches[0]


def collection_map(
    con: sqlite3.Connection, library_id: int
) -> dict[int, dict[str, Any]]:
    rows = con.execute(
        """
        SELECT collectionID, collectionName, parentCollectionID, key
        FROM collections
        WHERE libraryID=? AND collectionID NOT IN
              (SELECT collectionID FROM deletedCollections)
        """,
        (library_id,),
    ).fetchall()
    return {r["collectionID"]: dict(r) for r in rows}


def collection_path(
    collection_id: int, collections: dict[int, dict[str, Any]]
) -> str:
    names: list[str] = []
    seen: set[int] = set()
    current: int | None = collection_id
    while current and current not in seen and current in collections:
        seen.add(current)
        row = collections[current]
        names.append(row["collectionName"])
        current = row["parentCollectionID"]
    return "/".join(reversed(names))


def resolve_collection(
    con: sqlite3.Connection, library_id: int, selector: str
) -> tuple[int, str]:
    collections = collection_map(con, library_id)
    wanted = selector.strip().replace("\\", "/").strip("/")
    paths = {cid: collection_path(cid, collections) for cid in collections}
    if "/" in wanted:
        matches = [cid for cid, path in paths.items() if path.casefold() == wanted.casefold()]
    else:
        matches = [
            cid
            for cid, row in collections.items()
            if row["collectionName"].casefold() == wanted.casefold()
        ]
    if len(matches) != 1:
        candidates = [path for path in paths.values() if wanted.casefold() in path.casefold()]
        detail = ", ".join(sorted(candidates)) or "none"
        fail(f"collection {selector!r} not uniquely found; matching paths: {detail}")
    cid = matches[0]
    return cid, paths[cid]


def descendant_ids(
    con: sqlite3.Connection, collection_id: int, recursive: bool
) -> list[int]:
    if not recursive:
        return [collection_id]
    rows = con.execute(
        """
        WITH RECURSIVE tree(collectionID) AS (
          SELECT ?
          UNION ALL
          SELECT c.collectionID FROM collections c
          JOIN tree t ON c.parentCollectionID=t.collectionID
        )
        SELECT collectionID FROM tree
        """,
        (collection_id,),
    ).fetchall()
    return [r[0] for r in rows]


def item_ids_for_collection(
    con: sqlite3.Connection, collection_id: int, recursive: bool
) -> list[int]:
    ids = descendant_ids(con, collection_id, recursive)
    placeholders = ",".join("?" for _ in ids)
    rows = con.execute(
        f"""
        SELECT DISTINCT ci.itemID
        FROM collectionItems ci
        JOIN items i ON i.itemID=ci.itemID
        JOIN itemTypes it ON it.itemTypeID=i.itemTypeID
        LEFT JOIN deletedItems d ON d.itemID=i.itemID
        WHERE ci.collectionID IN ({placeholders})
          AND d.itemID IS NULL
          AND it.typeName NOT IN ('attachment','note','annotation')
        ORDER BY ci.itemID
        """,
        ids,
    ).fetchall()
    return [r[0] for r in rows]


def field_values(con: sqlite3.Connection, item_id: int) -> dict[str, str]:
    rows = con.execute(
        """
        SELECT f.fieldName, v.value
        FROM itemData d JOIN fields f ON f.fieldID=d.fieldID
        JOIN itemDataValues v ON v.valueID=d.valueID
        WHERE d.itemID=?
        """,
        (item_id,),
    ).fetchall()
    return {r["fieldName"]: r["value"] for r in rows}


def creators(con: sqlite3.Connection, item_id: int) -> list[str]:
    rows = con.execute(
        """
        SELECT c.firstName, c.lastName
        FROM itemCreators ic JOIN creators c ON c.creatorID=ic.creatorID
        WHERE ic.itemID=? ORDER BY ic.orderIndex
        """,
        (item_id,),
    ).fetchall()
    return [
        " ".join(part for part in [r["firstName"], r["lastName"]] if part).strip()
        for r in rows
    ]


def tags(con: sqlite3.Connection, item_id: int) -> list[str]:
    rows = con.execute(
        """
        SELECT t.name FROM itemTags it JOIN tags t ON t.tagID=it.tagID
        WHERE it.itemID=? ORDER BY t.name
        """,
        (item_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def memberships(con: sqlite3.Connection, item_id: int) -> list[str]:
    lib = con.execute("SELECT libraryID FROM items WHERE itemID=?", (item_id,)).fetchone()
    if not lib:
        return []
    collections = collection_map(con, lib["libraryID"])
    rows = con.execute(
        "SELECT collectionID FROM collectionItems WHERE itemID=?", (item_id,)
    ).fetchall()
    return sorted(
        collection_path(r["collectionID"], collections)
        for r in rows
        if r["collectionID"] in collections
    )


def attachment_rows(
    con: sqlite3.Connection, parent_id: int, data_dir: Path
) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT i.key, ia.contentType, ia.path, ia.linkMode
        FROM itemAttachments ia JOIN items i ON i.itemID=ia.itemID
        LEFT JOIN deletedItems d ON d.itemID=i.itemID
        WHERE ia.parentItemID=? AND d.itemID IS NULL
        ORDER BY i.itemID
        """,
        (parent_id,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        path = row["path"]
        resolved: str | None = None
        if path and path.startswith("storage:"):
            resolved = str(data_dir / "storage" / row["key"] / path[len("storage:") :])
        elif path:
            resolved = path
        result.append(
            {
                "key": row["key"],
                "contentType": row["contentType"],
                "storedPath": path,
                "resolvedPath": resolved,
                "exists": bool(resolved and Path(resolved).exists()),
            }
        )
    return result


def item_record(
    con: sqlite3.Connection, item_id: int, data_dir: Path
) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT i.itemID, i.key, i.libraryID, it.typeName
        FROM items i JOIN itemTypes it ON it.itemTypeID=i.itemTypeID
        WHERE i.itemID=?
        """,
        (item_id,),
    ).fetchone()
    if not row:
        fail(f"item ID {item_id} not found")
    values = field_values(con, item_id)
    preferred = [
        "title",
        "date",
        "DOI",
        "url",
        "publicationTitle",
        "publisher",
        "repository",
        "archiveID",
        "citationKey",
        "abstractNote",
        "extra",
    ]
    metadata = {name: values[name] for name in preferred if values.get(name)}
    metadata.update(
        {name: value for name, value in values.items() if name not in metadata and value}
    )
    return {
        "itemID": row["itemID"],
        "key": row["key"],
        "libraryID": row["libraryID"],
        "itemType": row["typeName"],
        **metadata,
        "creators": creators(con, item_id),
        "tags": tags(con, item_id),
        "collections": memberships(con, item_id),
        "attachments": attachment_rows(con, item_id, data_dir),
    }


def compact_item(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in [
            "key",
            "itemType",
            "title",
            "date",
            "DOI",
            "citationKey",
            "creators",
            "collections",
            "attachments",
        ]
        if record.get(key) not in (None, "", [])
    }


def emit(data: Any, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    rows = data if isinstance(data, list) else [data]
    flat: list[dict[str, Any]] = []
    for row in rows:
        converted = {
            key: (
                json.dumps(value, ensure_ascii=False)
                if isinstance(value, (list, dict))
                else value
            )
            for key, value in row.items()
        }
        flat.append(converted)
    if not flat:
        print("(no results)")
        return
    if output_format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)
        return
    columns = list(flat[0])
    widths = {
        col: min(60, max(len(col), *(len(str(row.get(col, ""))) for row in flat)))
        for col in columns
    }
    print(" | ".join(col.ljust(widths[col]) for col in columns))
    print("-+-".join("-" * widths[col] for col in columns))
    for row in flat:
        print(
            " | ".join(
                str(row.get(col, "")).replace("\n", " ")[: widths[col]].ljust(widths[col])
                for col in columns
            )
        )


def command_locate(args: argparse.Namespace) -> None:
    rows = []
    for path in locate_data_dirs():
        db = path / "zotero.sqlite"
        rows.append(
            {
                "dataDir": str(path),
                "database": str(db),
                "databaseBytes": db.stat().st_size,
                "modified": db.stat().st_mtime,
            }
        )
    emit(rows, args.format)


def command_libraries(
    args: argparse.Namespace, con: sqlite3.Connection, _: Path
) -> None:
    emit(library_rows(con), args.format)


def command_collections(
    args: argparse.Namespace, con: sqlite3.Connection, _: Path
) -> None:
    library = resolve_library(con, args.library)
    collections = collection_map(con, library["libraryID"])
    rows: list[dict[str, Any]] = []
    for cid, row in collections.items():
        direct = len(item_ids_for_collection(con, cid, False))
        recursive = len(item_ids_for_collection(con, cid, True))
        rows.append(
            {
                "key": row["key"],
                "path": collection_path(cid, collections),
                "directItems": direct,
                "recursiveItems": recursive,
            }
        )
    emit(sorted(rows, key=lambda row: row["path"].casefold()), args.format)


def command_items(
    args: argparse.Namespace, con: sqlite3.Connection, data_dir: Path
) -> None:
    library = resolve_library(con, args.library)
    cid, path = resolve_collection(con, library["libraryID"], args.collection)
    ids = item_ids_for_collection(con, cid, not args.direct)
    records = [compact_item(item_record(con, item_id, data_dir)) for item_id in ids]
    if args.limit is not None:
        records = records[: args.limit]
    payload = {
        "library": library["name"],
        "collection": path,
        "recursive": not args.direct,
        "count": len(records),
        "items": records,
    }
    emit(payload if args.format == "json" else records, args.format)


def command_bundle(
    args: argparse.Namespace, con: sqlite3.Connection, data_dir: Path
) -> None:
    library = resolve_library(con, args.library)
    cid, path = resolve_collection(con, library["libraryID"], args.collection)
    ids = item_ids_for_collection(con, cid, not args.direct)
    if args.limit is not None:
        ids = ids[: args.limit]
    records = [item_record(con, item_id, data_dir) for item_id in ids]
    emit(
        {
            "dataDir": str(data_dir),
            "library": library["name"],
            "libraryID": library["libraryID"],
            "collection": path,
            "recursive": not args.direct,
            "count": len(records),
            "items": records,
        },
        args.format,
    )


def command_obsidian(
    args: argparse.Namespace, con: sqlite3.Connection, data_dir: Path
) -> None:
    from .graph import export_obsidian

    library = resolve_library(con, args.library)
    cid, path = resolve_collection(con, library["libraryID"], args.collection)
    ids = item_ids_for_collection(con, cid, not args.direct)
    if args.limit is not None:
        ids = ids[: args.limit]
    bundle = {
        "dataDir": str(data_dir),
        "library": library["name"],
        "libraryID": library["libraryID"],
        "collection": path,
        "recursive": not args.direct,
        "count": len(ids),
        "items": [item_record(con, item_id, data_dir) for item_id in ids],
    }
    relations = None
    if args.relations:
        relations = json.loads(
            Path(args.relations).read_text(encoding="utf-8")
        )
        if not isinstance(relations, list):
            fail("--relations must contain a JSON array")
    emit(export_obsidian(bundle, args.output_dir, relations), args.format)


def command_item(
    args: argparse.Namespace, con: sqlite3.Connection, data_dir: Path
) -> None:
    row = con.execute(
        """
        SELECT i.itemID FROM items i LEFT JOIN deletedItems d ON d.itemID=i.itemID
        WHERE i.key=? AND d.itemID IS NULL
        """,
        (args.key.upper(),),
    ).fetchone()
    if not row:
        fail(f"item key {args.key!r} not found")
    emit(item_record(con, row["itemID"], data_dir), args.format)


def command_attachment(
    args: argparse.Namespace, con: sqlite3.Connection, data_dir: Path
) -> None:
    row = con.execute(
        """
        SELECT i.itemID, i.key, ia.parentItemID, ia.contentType, ia.path
        FROM items i JOIN itemAttachments ia ON ia.itemID=i.itemID
        LEFT JOIN deletedItems d ON d.itemID=i.itemID
        WHERE i.key=? AND d.itemID IS NULL
        """,
        (args.key.upper(),),
    ).fetchone()
    if not row:
        fail(f"attachment key {args.key!r} not found")
    path = row["path"]
    resolved = (
        str(data_dir / "storage" / row["key"] / path[len("storage:") :])
        if path and path.startswith("storage:")
        else path
    )
    payload = {
        "attachmentKey": row["key"],
        "contentType": row["contentType"],
        "storedPath": path,
        "resolvedPath": resolved,
        "exists": bool(resolved and Path(resolved).exists()),
        "parent": (
            item_record(con, row["parentItemID"], data_dir)
            if row["parentItemID"]
            else None
        ),
    }
    emit(payload, args.format)


def command_search(
    args: argparse.Namespace, con: sqlite3.Connection, data_dir: Path
) -> None:
    library = resolve_library(con, args.library)
    allowed: set[int] | None = None
    if args.collection:
        cid, _ = resolve_collection(con, library["libraryID"], args.collection)
        allowed = set(item_ids_for_collection(con, cid, not args.direct))
    term = f"%{args.query.casefold()}%"
    rows = con.execute(
        """
        SELECT DISTINCT i.itemID
        FROM items i JOIN itemTypes it ON it.itemTypeID=i.itemTypeID
        LEFT JOIN itemData d ON d.itemID=i.itemID
        LEFT JOIN itemDataValues v ON v.valueID=d.valueID
        LEFT JOIN itemCreators ic ON ic.itemID=i.itemID
        LEFT JOIN creators c ON c.creatorID=ic.creatorID
        LEFT JOIN deletedItems di ON di.itemID=i.itemID
        WHERE i.libraryID=? AND di.itemID IS NULL
          AND it.typeName NOT IN ('attachment','note','annotation')
          AND (LOWER(COALESCE(v.value,'')) LIKE ?
               OR LOWER(COALESCE(c.firstName,'') || ' ' || COALESCE(c.lastName,'')) LIKE ?)
        ORDER BY i.itemID
        """,
        (library["libraryID"], term, term),
    ).fetchall()
    ids = [r["itemID"] for r in rows if allowed is None or r["itemID"] in allowed]
    if args.limit is not None:
        ids = ids[: args.limit]
    records = [compact_item(item_record(con, item_id, data_dir)) for item_id in ids]
    emit(records, args.format)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read local Zotero libraries without modifying the live database."
    )
    parser.add_argument("--data-dir", help="directory containing zotero.sqlite")
    parser.add_argument(
        "--format", choices=["json", "table", "csv"], default="json"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("locate", help="locate Zotero data directories")
    sub.add_parser("libraries", help="list personal and group libraries")

    collections = sub.add_parser("collections", help="list collection paths")
    collections.add_argument("--library", default="My Library")

    items = sub.add_parser("items", help="list bibliographic items in a collection")
    items.add_argument("--library", default="My Library")
    items.add_argument("--collection", required=True)
    items.add_argument("--direct", action="store_true", help="exclude descendants")
    items.add_argument("--limit", type=int)

    bundle = sub.add_parser(
        "bundle", help="return full collection metadata and resolved attachment paths"
    )
    bundle.add_argument("--library", default="My Library")
    bundle.add_argument("--collection", required=True)
    bundle.add_argument("--direct", action="store_true", help="exclude descendants")
    bundle.add_argument("--limit", type=int)

    obsidian = sub.add_parser(
        "obsidian", help="export an Obsidian-compatible metadata network"
    )
    obsidian.add_argument("--library", default="My Library")
    obsidian.add_argument("--collection", required=True)
    obsidian.add_argument("--output-dir", required=True)
    obsidian.add_argument(
        "--relations", help="optional JSON array of semantic paper relationships"
    )
    obsidian.add_argument("--direct", action="store_true", help="exclude descendants")
    obsidian.add_argument("--limit", type=int)

    item = sub.add_parser("item", help="inspect an item by Zotero key")
    item.add_argument("--key", required=True)

    attachment = sub.add_parser(
        "attachment", help="resolve a storage attachment key and its parent item"
    )
    attachment.add_argument("--key", required=True)

    search = sub.add_parser("search", help="search metadata and creators")
    search.add_argument("--query", required=True)
    search.add_argument("--library", default="My Library")
    search.add_argument("--collection")
    search.add_argument("--direct", action="store_true", help="exclude descendants")
    search.add_argument("--limit", type=int)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "locate":
        command_locate(args)
        return
    data_dir = resolve_data_dir(args.data_dir)
    commands = {
        "libraries": command_libraries,
        "collections": command_collections,
        "items": command_items,
        "bundle": command_bundle,
        "obsidian": command_obsidian,
        "item": command_item,
        "attachment": command_attachment,
        "search": command_search,
    }
    with snapshot_connection(data_dir) as con:
        commands[args.command](args, con, data_dir)


if __name__ == "__main__":
    main()
