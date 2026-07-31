"""Read cached full text, notes, and annotations from a Zotero snapshot."""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import sqlite3
from typing import Any


class _NoteTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in {"br", "div", "p", "li", "blockquote", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"div", "p", "li", "blockquote", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_note_html(value: str | None) -> str:
    if not value:
        return ""
    parser = _NoteTextParser()
    parser.feed(value)
    text = unescape("".join(parser.parts))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _item_title(con: sqlite3.Connection, item_id: int) -> str:
    row = con.execute(
        """
        SELECT v.value
        FROM itemData d
        JOIN fields f ON f.fieldID=d.fieldID AND f.fieldName='title'
        JOIN itemDataValues v ON v.valueID=d.valueID
        WHERE d.itemID=?
        LIMIT 1
        """,
        (item_id,),
    ).fetchone()
    return row[0] if row else f"Item {item_id}"


def annotation_digest(
    con: sqlite3.Connection,
    item_ids: list[int],
    limit: int = 500,
) -> dict[str, Any]:
    """Group child notes and PDF annotations by bibliographic item."""
    limit = max(1, min(int(limit), 5000))
    remaining = limit
    papers: list[dict[str, Any]] = []
    total_annotations = 0
    total_notes = 0

    for item_id in item_ids:
        if remaining <= 0:
            break
        item = con.execute(
            "SELECT key FROM items WHERE itemID=?", (item_id,)
        ).fetchone()
        if not item:
            continue

        notes: list[dict[str, Any]] = []
        note_rows = con.execute(
            """
            SELECT i.key, n.title, n.note
            FROM itemNotes n
            JOIN items i ON i.itemID=n.itemID
            LEFT JOIN deletedItems d ON d.itemID=i.itemID
            WHERE n.parentItemID=? AND d.itemID IS NULL
            ORDER BY i.dateAdded, i.itemID
            """,
            (item_id,),
        ).fetchall()
        for row in note_rows:
            if remaining <= 0:
                break
            text = clean_note_html(row["note"])
            if not text:
                continue
            notes.append(
                {
                    "key": row["key"],
                    "title": row["title"] or "",
                    "text": text,
                }
            )
            total_notes += 1
            remaining -= 1

        annotations: list[dict[str, Any]] = []
        annotation_rows = con.execute(
            """
            SELECT ai.key, att.key AS attachmentKey, a.type, a.authorName,
                   a.text, a.comment, a.color, a.pageLabel, a.sortIndex
            FROM itemAnnotations a
            JOIN items ai ON ai.itemID=a.itemID
            JOIN itemAttachments ia ON ia.itemID=a.parentItemID
            JOIN items att ON att.itemID=a.parentItemID
            LEFT JOIN deletedItems d ON d.itemID=ai.itemID
            WHERE ia.parentItemID=? AND d.itemID IS NULL
            ORDER BY a.sortIndex, ai.itemID
            """,
            (item_id,),
        ).fetchall()
        for row in annotation_rows:
            if remaining <= 0:
                break
            text = (row["text"] or "").strip()
            comment = (row["comment"] or "").strip()
            if not text and not comment:
                continue
            annotations.append(
                {
                    "key": row["key"],
                    "attachmentKey": row["attachmentKey"],
                    "type": row["type"],
                    "pageLabel": row["pageLabel"] or "",
                    "text": text,
                    "comment": comment,
                    "color": row["color"] or "",
                    "author": row["authorName"] or "",
                }
            )
            total_annotations += 1
            remaining -= 1

        if notes or annotations:
            papers.append(
                {
                    "key": item["key"],
                    "title": _item_title(con, item_id),
                    "annotationCount": len(annotations),
                    "noteCount": len(notes),
                    "annotations": annotations,
                    "notes": notes,
                }
            )

    return {
        "paperCount": len(papers),
        "annotationCount": total_annotations,
        "noteCount": total_notes,
        "limit": limit,
        "truncated": remaining == 0,
        "papers": papers,
    }


def cached_fulltext(
    con: sqlite3.Connection,
    data_dir: Path,
    key: str,
    max_chars: int = 200_000,
) -> dict[str, Any]:
    """Read Zotero's local `.zotero-ft-cache` for an item or attachment."""
    max_chars = max(1_000, min(int(max_chars), 2_000_000))
    item = con.execute(
        """
        SELECT i.itemID, i.key, it.typeName
        FROM items i JOIN itemTypes it ON it.itemTypeID=i.itemTypeID
        LEFT JOIN deletedItems d ON d.itemID=i.itemID
        WHERE UPPER(i.key)=UPPER(?) AND d.itemID IS NULL
        """,
        (key,),
    ).fetchone()
    if not item:
        raise KeyError(f"item key {key!r} not found")

    if item["typeName"] == "attachment":
        rows = con.execute(
            """
            SELECT i.key, ia.contentType, ia.path, ia.parentItemID
            FROM itemAttachments ia JOIN items i ON i.itemID=ia.itemID
            WHERE ia.itemID=?
            """,
            (item["itemID"],),
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT i.key, ia.contentType, ia.path, ia.parentItemID
            FROM itemAttachments ia JOIN items i ON i.itemID=ia.itemID
            LEFT JOIN deletedItems d ON d.itemID=i.itemID
            WHERE ia.parentItemID=? AND d.itemID IS NULL
            ORDER BY CASE WHEN ia.contentType='application/pdf' THEN 0 ELSE 1 END,
                     i.itemID
            """,
            (item["itemID"],),
        ).fetchall()

    attachments: list[dict[str, Any]] = []
    for row in rows:
        cache_path = data_dir / "storage" / row["key"] / ".zotero-ft-cache"
        record: dict[str, Any] = {
            "attachmentKey": row["key"],
            "contentType": row["contentType"],
            "cachePath": str(cache_path),
            "available": cache_path.is_file(),
        }
        if cache_path.is_file():
            text = cache_path.read_text(encoding="utf-8", errors="replace")
            record.update(
                {
                    "totalChars": len(text),
                    "returnedChars": min(len(text), max_chars),
                    "truncated": len(text) > max_chars,
                    "text": text[:max_chars],
                }
            )
        attachments.append(record)

    return {
        "requestedKey": item["key"],
        "itemType": item["typeName"],
        "maxCharsPerAttachment": max_chars,
        "attachments": attachments,
        "availableCount": sum(1 for row in attachments if row["available"]),
    }
