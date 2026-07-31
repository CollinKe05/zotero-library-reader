# MCP deployment

The MCP adapter uses the official Python MCP SDK and exposes read-only tools. The CLI has no external dependencies.

## Install

From the skill/project directory:

`python -m pip install -e ".[mcp]"`

## Stdio

Use this server command in any MCP client:

`python <skill-dir>/scripts/zotero_mcp.py`

Set `ZOTERO_DATA_DIR` when automatic discovery finds more than one library:

`C:\Users\name\Zotero`

Example client configuration:

```json
{
  "mcpServers": {
    "zotero-local": {
      "command": "python",
      "args": ["<skill-dir>/scripts/zotero_mcp.py"],
      "env": {
        "ZOTERO_DATA_DIR": "C:\\Users\\name\\Zotero"
      }
    }
  }
}
```

## Streamable HTTP

Set `ZOTERO_MCP_TRANSPORT=streamable-http` before starting the same server. Bind it only to a trusted interface because Zotero metadata and local attachment paths are private.

## Tools

- `zotero_locate_data_dirs`
- `zotero_list_libraries`
- `zotero_list_collections`
- `zotero_list_items`
- `zotero_get_collection_bundle`
- `zotero_get_item`
- `zotero_resolve_attachment`
- `zotero_search`

The MCP surface intentionally has no write or export tool. Obsidian export remains a CLI/user-authorized workflow.
