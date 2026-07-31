"""Official-SDK MCP adapter for ZoteroService."""

from __future__ import annotations

import os
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised without optional extra
    raise SystemExit(
        'MCP support is optional. Install with: pip install "mcp>=1.27,<2"'
    ) from exc

from .service import ZoteroService


mcp = FastMCP(
    "Zotero Local Reader",
    instructions=(
        "Read local Zotero libraries through validated temporary snapshots. "
        "All exposed tools are read-only."
    ),
    json_response=True,
)


def service(data_dir: str | None = None) -> ZoteroService:
    return ZoteroService(data_dir or os.environ.get("ZOTERO_DATA_DIR"))


@mcp.tool()
def zotero_locate_data_dirs() -> list[dict[str, Any]]:
    """Locate local Zotero data directories containing zotero.sqlite."""
    return ZoteroService.locate()


@mcp.tool()
def zotero_list_libraries(data_dir: str | None = None) -> list[dict[str, Any]]:
    """List personal and group libraries in a Zotero data directory."""
    return service(data_dir).libraries()


@mcp.tool()
def zotero_list_collections(
    library: str = "My Library", data_dir: str | None = None
) -> list[dict[str, Any]]:
    """List full collection paths and unique item counts."""
    return service(data_dir).collections(library)


@mcp.tool()
def zotero_list_items(
    collection: str,
    library: str = "My Library",
    recursive: bool = True,
    limit: int | None = None,
    data_dir: str | None = None,
) -> dict[str, Any]:
    """List bibliographic records in a collection; descendants are included by default."""
    return service(data_dir).collection_items(
        collection, library, recursive, limit, full=False
    )


@mcp.tool()
def zotero_get_collection_bundle(
    collection: str,
    library: str = "My Library",
    recursive: bool = True,
    limit: int | None = None,
    data_dir: str | None = None,
) -> dict[str, Any]:
    """Get full metadata, abstracts, tags, and resolved PDF paths for analysis."""
    return service(data_dir).collection_bundle(
        collection, library, recursive, limit
    )


@mcp.tool()
def zotero_get_item(key: str, data_dir: str | None = None) -> dict[str, Any]:
    """Get full metadata and attachments for one Zotero item key."""
    return service(data_dir).item(key)


@mcp.tool()
def zotero_resolve_attachment(
    key: str, data_dir: str | None = None
) -> dict[str, Any]:
    """Resolve a Zotero storage key to its local file and parent bibliographic item."""
    return service(data_dir).attachment(key)


@mcp.tool()
def zotero_search(
    query: str,
    library: str = "My Library",
    collection: str | None = None,
    recursive: bool = True,
    limit: int = 50,
    data_dir: str | None = None,
) -> list[dict[str, Any]]:
    """Search metadata, abstracts, citation keys, DOI values, and creators."""
    return service(data_dir).search(
        query, library, collection, recursive, limit
    )


@mcp.tool()
def zotero_get_cached_fulltext(
    key: str,
    max_chars: int = 200_000,
    data_dir: str | None = None,
) -> dict[str, Any]:
    """Read Zotero's cached full text for an item or attachment key."""
    return service(data_dir).cached_fulltext(key, max_chars)


@mcp.tool()
def zotero_get_annotation_digest(
    collection: str,
    library: str = "My Library",
    recursive: bool = True,
    limit: int = 500,
    data_dir: str | None = None,
) -> dict[str, Any]:
    """Group child notes and PDF annotations by bibliographic item."""
    return service(data_dir).annotation_digest(
        collection, library, recursive, limit
    )


@mcp.tool()
def zotero_scite_item(
    key: str | None = None,
    doi: str | None = None,
    timeout: int = 15,
    data_dir: str | None = None,
) -> dict[str, Any]:
    """Fetch Scite citation tallies and editorial notices for one DOI or item."""
    return service(data_dir).scite_item(key, doi, timeout)


@mcp.tool()
def zotero_scite_collection(
    collection: str,
    library: str = "My Library",
    recursive: bool = True,
    limit: int = 500,
    timeout: int = 15,
    data_dir: str | None = None,
) -> dict[str, Any]:
    """Batch-enrich a collection with Scite citation intelligence."""
    return service(data_dir).scite_collection(
        collection, library, recursive, limit, timeout
    )


def main() -> None:
    transport = os.environ.get("ZOTERO_MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)
