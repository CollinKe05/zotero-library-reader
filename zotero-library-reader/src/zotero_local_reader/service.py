"""Stable application service used by both CLI and MCP adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import backend
from .content import annotation_digest as build_annotation_digest
from .content import cached_fulltext as read_cached_fulltext
from .scite import enrich_doi, enrich_items


class ZoteroService:
    """Read-only façade over a local Zotero data directory."""

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = backend.resolve_data_dir(str(data_dir) if data_dir else None)

    @staticmethod
    def locate() -> list[dict[str, Any]]:
        result = []
        for path in backend.locate_data_dirs():
            db = path / "zotero.sqlite"
            result.append(
                {
                    "dataDir": str(path),
                    "database": str(db),
                    "databaseBytes": db.stat().st_size,
                    "modified": db.stat().st_mtime,
                }
            )
        return result

    def libraries(self) -> list[dict[str, Any]]:
        with backend.snapshot_connection(self.data_dir) as con:
            return backend.library_rows(con)

    def collections(self, library: str = "My Library") -> list[dict[str, Any]]:
        with backend.snapshot_connection(self.data_dir) as con:
            selected = backend.resolve_library(con, library)
            collection_rows = backend.collection_map(con, selected["libraryID"])
            result = []
            for cid, row in collection_rows.items():
                result.append(
                    {
                        "key": row["key"],
                        "path": backend.collection_path(cid, collection_rows),
                        "directItems": len(
                            backend.item_ids_for_collection(con, cid, False)
                        ),
                        "recursiveItems": len(
                            backend.item_ids_for_collection(con, cid, True)
                        ),
                    }
                )
            return sorted(result, key=lambda row: row["path"].casefold())

    def collection_items(
        self,
        collection: str,
        library: str = "My Library",
        recursive: bool = True,
        limit: int | None = None,
        full: bool = False,
    ) -> dict[str, Any]:
        with backend.snapshot_connection(self.data_dir) as con:
            selected = backend.resolve_library(con, library)
            cid, path = backend.resolve_collection(
                con, selected["libraryID"], collection
            )
            ids = backend.item_ids_for_collection(con, cid, recursive)
            if limit is not None:
                ids = ids[:limit]
            records = [
                backend.item_record(con, item_id, self.data_dir) for item_id in ids
            ]
            if not full:
                records = [backend.compact_item(record) for record in records]
            return {
                "dataDir": str(self.data_dir),
                "library": selected["name"],
                "libraryID": selected["libraryID"],
                "collection": path,
                "recursive": recursive,
                "count": len(records),
                "items": records,
            }

    def item(self, key: str) -> dict[str, Any]:
        with backend.snapshot_connection(self.data_dir) as con:
            row = con.execute(
                """
                SELECT i.itemID FROM items i
                LEFT JOIN deletedItems d ON d.itemID=i.itemID
                WHERE UPPER(i.key)=UPPER(?) AND d.itemID IS NULL
                """,
                (key,),
            ).fetchone()
            if not row:
                backend.fail(f"item key {key!r} not found")
            return backend.item_record(con, row["itemID"], self.data_dir)

    def attachment(self, key: str) -> dict[str, Any]:
        with backend.snapshot_connection(self.data_dir) as con:
            row = con.execute(
                """
                SELECT i.itemID, i.key, ia.parentItemID, ia.contentType, ia.path
                FROM items i JOIN itemAttachments ia ON ia.itemID=i.itemID
                LEFT JOIN deletedItems d ON d.itemID=i.itemID
                WHERE UPPER(i.key)=UPPER(?) AND d.itemID IS NULL
                """,
                (key,),
            ).fetchone()
            if not row:
                backend.fail(f"attachment key {key!r} not found")
            stored = row["path"]
            resolved = (
                str(
                    self.data_dir
                    / "storage"
                    / row["key"]
                    / stored[len("storage:") :]
                )
                if stored and stored.startswith("storage:")
                else stored
            )
            return {
                "attachmentKey": row["key"],
                "contentType": row["contentType"],
                "storedPath": stored,
                "resolvedPath": resolved,
                "exists": bool(resolved and Path(resolved).exists()),
                "parent": (
                    backend.item_record(con, row["parentItemID"], self.data_dir)
                    if row["parentItemID"]
                    else None
                ),
            }

    def search(
        self,
        query: str,
        library: str = "My Library",
        collection: str | None = None,
        recursive: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with backend.snapshot_connection(self.data_dir) as con:
            selected = backend.resolve_library(con, library)
            allowed: set[int] | None = None
            if collection:
                cid, _ = backend.resolve_collection(
                    con, selected["libraryID"], collection
                )
                allowed = set(
                    backend.item_ids_for_collection(con, cid, recursive)
                )
            term = f"%{query.casefold()}%"
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
                       OR LOWER(COALESCE(c.firstName,'') || ' ' ||
                                COALESCE(c.lastName,'')) LIKE ?)
                ORDER BY i.itemID
                """,
                (selected["libraryID"], term, term),
            ).fetchall()
            ids = [
                row["itemID"]
                for row in rows
                if allowed is None or row["itemID"] in allowed
            ][:limit]
            return [
                backend.compact_item(
                    backend.item_record(con, item_id, self.data_dir)
                )
                for item_id in ids
            ]

    def collection_bundle(
        self,
        collection: str,
        library: str = "My Library",
        recursive: bool = True,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return full metadata, abstracts, tags, and resolved attachment paths."""
        return self.collection_items(
            collection=collection,
            library=library,
            recursive=recursive,
            limit=limit,
            full=True,
        )

    def annotation_digest(
        self,
        collection: str,
        library: str = "My Library",
        recursive: bool = True,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Collect child notes and PDF annotations grouped by paper."""
        with backend.snapshot_connection(self.data_dir) as con:
            selected = backend.resolve_library(con, library)
            cid, path = backend.resolve_collection(
                con, selected["libraryID"], collection
            )
            ids = backend.item_ids_for_collection(con, cid, recursive)
            digest = build_annotation_digest(con, ids, limit)
            return {
                "dataDir": str(self.data_dir),
                "library": selected["name"],
                "collection": path,
                "recursive": recursive,
                **digest,
            }

    def cached_fulltext(
        self,
        key: str,
        max_chars: int = 200_000,
    ) -> dict[str, Any]:
        """Read Zotero's cached full text for an item or attachment key."""
        with backend.snapshot_connection(self.data_dir) as con:
            try:
                return read_cached_fulltext(con, self.data_dir, key, max_chars)
            except KeyError as exc:
                backend.fail(str(exc))

    def scite_item(
        self,
        key: str | None = None,
        doi: str | None = None,
        timeout: int = 15,
    ) -> dict[str, Any]:
        """Fetch Scite citation tallies and editorial notices for one paper."""
        record: dict[str, Any] | None = None
        if not doi:
            if not key:
                backend.fail("provide either key or DOI")
            record = self.item(key)
            doi = record.get("DOI")
        if not doi:
            backend.fail(f"no DOI found for item key {key!r}")
        result = enrich_doi(doi, timeout)
        if record:
            result["zoteroKey"] = record["key"]
            result["zoteroTitle"] = record.get("title")
        return result

    def scite_collection(
        self,
        collection: str,
        library: str = "My Library",
        recursive: bool = True,
        limit: int = 500,
        timeout: int = 15,
    ) -> dict[str, Any]:
        """Batch-enrich collection metadata with Scite citation intelligence."""
        bundle = self.collection_items(
            collection=collection,
            library=library,
            recursive=recursive,
            limit=limit,
            full=True,
        )
        result = enrich_items(bundle["items"], timeout)
        return {
            "library": bundle["library"],
            "collection": bundle["collection"],
            "recursive": recursive,
            **result,
        }
