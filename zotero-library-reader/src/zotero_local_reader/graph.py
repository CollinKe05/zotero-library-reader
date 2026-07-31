"""Metadata graph and Obsidian-compatible Markdown export."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def safe_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned[:120] or fallback).strip()


def yaml_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def metadata_graph(items: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_node(node_id: str, kind: str, label: str) -> None:
        nodes.setdefault(node_id, {"id": node_id, "kind": kind, "label": label})

    def add_edge(source: str, target: str, relation: str) -> None:
        key = (source, target, relation)
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append(
                {"source": source, "target": target, "relation": relation}
            )

    for item in items:
        paper = f'paper:{item["key"]}'
        add_node(paper, "paper", item.get("title") or item["key"])
        for collection in item.get("collections", []):
            node = f"collection:{collection}"
            add_node(node, "collection", collection)
            add_edge(paper, node, "in_collection")
        for creator in item.get("creators", []):
            node = f"creator:{creator}"
            add_node(node, "creator", creator)
            add_edge(paper, node, "authored_by")
        for tag in item.get("tags", []):
            node = f"tag:{tag}"
            add_node(node, "tag", tag)
            add_edge(paper, node, "tagged")
    return {"nodes": list(nodes.values()), "edges": edges}


def export_obsidian(
    bundle: dict[str, Any],
    output_dir: str | Path,
    semantic_relations: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Export metadata notes and optional LLM-supplied paper relationships."""
    root = Path(output_dir).expanduser().resolve()
    papers_dir = root / "Papers"
    collections_dir = root / "Collections"
    creators_dir = root / "Creators"
    for folder in (papers_dir, collections_dir, creators_dir):
        folder.mkdir(parents=True, exist_ok=True)

    items = bundle["items"]
    note_names = {
        item["key"]: safe_name(
            f'{item.get("title") or "Untitled"} — {item["key"]}', item["key"]
        )
        for item in items
    }
    relation_map: dict[str, list[dict[str, str]]] = {}
    for relation in semantic_relations or []:
        relation_map.setdefault(relation["source"], []).append(relation)

    collection_links: dict[str, list[str]] = {}
    creator_links: dict[str, list[str]] = {}
    for item in items:
        key = item["key"]
        title = item.get("title") or key
        lines = [
            "---",
            f"zotero_key: {yaml_string(key)}",
            f"title: {yaml_string(title)}",
            f"item_type: {yaml_string(item.get('itemType', ''))}",
        ]
        for field in ("date", "DOI", "url", "citationKey"):
            if item.get(field):
                lines.append(f"{field}: {yaml_string(item[field])}")
        lines.extend(["---", "", f"# {title}", ""])
        creators = item.get("creators", [])
        if creators:
            links = [f"[[Creators/{safe_name(c, 'Unknown')}|{c}]]" for c in creators]
            lines.extend([f"**作者：** {', '.join(links)}", ""])
            for creator in creators:
                creator_links.setdefault(creator, []).append(note_names[key])
        collections = item.get("collections", [])
        if collections:
            links = [
                f"[[Collections/{safe_name(c, 'Collection')}|{c}]]"
                for c in collections
            ]
            lines.extend([f"**分类：** {', '.join(links)}", ""])
            for collection in collections:
                collection_links.setdefault(collection, []).append(note_names[key])
        if item.get("abstractNote"):
            lines.extend(["## 摘要", "", item["abstractNote"], ""])
        attachments = [
            a["resolvedPath"]
            for a in item.get("attachments", [])
            if a.get("resolvedPath")
        ]
        if attachments:
            lines.extend(["## 本地附件", ""])
            lines.extend(f"- `{path}`" for path in attachments)
            lines.append("")
        relations = relation_map.get(key, [])
        if relations:
            lines.extend(["## 论文关系", ""])
            for relation in relations:
                target = relation["target"]
                target_name = note_names.get(target, target)
                label = relation.get("relation", "related_to")
                explanation = relation.get("explanation", "")
                lines.append(
                    f"- **{label}** → [[Papers/{target_name}|{target_name}]]"
                    + (f"：{explanation}" if explanation else "")
                )
            lines.append("")
        (papers_dir / f"{note_names[key]}.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )

    for collection, paper_names in collection_links.items():
        body = [f"# {collection}", ""] + [
            f"- [[Papers/{name}|{name}]]" for name in sorted(set(paper_names))
        ]
        (collections_dir / f"{safe_name(collection, 'Collection')}.md").write_text(
            "\n".join(body) + "\n", encoding="utf-8"
        )
    for creator, paper_names in creator_links.items():
        body = [f"# {creator}", ""] + [
            f"- [[Papers/{name}|{name}]]" for name in sorted(set(paper_names))
        ]
        (creators_dir / f"{safe_name(creator, 'Unknown')}.md").write_text(
            "\n".join(body) + "\n", encoding="utf-8"
        )

    graph = metadata_graph(items)
    (root / "graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    index = [
        f'# {bundle["collection"]}',
        "",
        f'- 文献数：{bundle["count"]}',
        f'- Zotero 文库：{bundle["library"]}',
        "",
        "## 文献",
        "",
    ] + [f"- [[Papers/{note_names[item['key']]}]]" for item in items]
    (root / "00-Index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return {
        "outputDir": str(root),
        "papers": len(items),
        "collections": len(collection_links),
        "creators": len(creator_links),
        "graphNodes": len(graph["nodes"]),
        "graphEdges": len(graph["edges"]),
        "semanticRelations": len(semantic_relations or []),
    }
