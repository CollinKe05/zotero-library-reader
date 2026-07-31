---
name: zotero-library-reader
description: Read and inspect local Zotero data directories, personal or group libraries, collection trees, bibliographic metadata, tags, and attachment paths without modifying the live database. Use when the user asks to access, browse, list, search, summarize, or export a local Zotero library or a named Zotero category/collection, or provides a Zotero storage key/path such as storage/ABCD1234.
---

# Zotero Library Reader

Use `scripts/zotero_cli.py` for deterministic, read-only access. It creates and validates a temporary database snapshot, so never query or modify the live `zotero.sqlite` directly. The same core is exposed through `scripts/zotero_mcp.py`.

## Workflow

1. Locate Zotero data directories:

   `python scripts/zotero_cli.py locate`

2. If the user names a Zotero library, resolve it:

   `python scripts/zotero_cli.py libraries`

   Treat “我的文库”, “个人文库”, “My Library”, and “user” as the personal library. Group-library names are resolved from Zotero's `groups` table.

3. Resolve the requested category as a collection path:

   `python scripts/zotero_cli.py collections --library "我的文库"`

   Accept either a unique leaf name such as `Policies` or a slash path such as `Research/Robotics/Policies`. If a leaf name is ambiguous, use the full path shown by the CLI.

4. Read the collection:

   `python scripts/zotero_cli.py items --library "My Library" --collection "Research/Robotics"`

   Collection reads include descendants by default and deduplicate items. Add `--direct` only when the user explicitly wants items assigned directly to that collection.

5. Inspect a specific bibliographic item or attachment:

   `python scripts/zotero_cli.py item --key PAPER123`

   `python scripts/zotero_cli.py attachment --key ABCD1234`

6. Search titles, DOI values, citation keys, abstracts, or creators:

   `python scripts/zotero_cli.py search --query "robot policy" --library "My Library" --collection "Research/Robotics"`

7. Prepare a collection for PDF or cross-paper analysis:

   `python scripts/zotero_cli.py bundle --library "My Library" --collection "Research/Robotics"`

   Read [references/synthesis.md](references/synthesis.md) completely when the user requests PDF explanation, comparison, collection-wide synthesis, a research map, or Obsidian export.

## MCP interface

Read [references/mcp.md](references/mcp.md) completely when installing, configuring, or exposing the MCP server. Keep the MCP interface read-only. It provides library, collection, item, attachment, search, and full collection-bundle tools.

Run:

`python scripts/zotero_mcp.py`

The reusable package is under `src/zotero_local_reader`; `ZoteroService` is the stable programmatic interface shared by CLI and MCP.

## Data-directory selection

- Prefer an explicit user path with `--data-dir`.
- Otherwise use `ZOTERO_DATA_DIR`, Zotero profile preferences, or conventional local paths.
- If multiple data directories exist, run `locate` and pass the intended one explicitly.
- Use `--format json` (default) for further analysis and `--format table` for a compact user-facing view.

## Safety and interpretation

- Keep all operations read-only. Temporary snapshots may be created under the operating system's temporary directory and are deleted after each command.
- Do not mistake the Zotero application directory (for example `C:\Program Files\Zotero`) for the data directory.
- A storage folder key identifies an attachment item; use `attachment` to resolve its parent bibliographic item and collection membership.
- Report collection item counts as unique bibliographic records. An item can belong to both a parent collection and a child collection.
- Only open or extract PDF content when the user requests content analysis; otherwise return the resolved attachment paths and metadata.
- Generate Obsidian notes or semantic relationship graphs only when the user explicitly requests them.

## CLI reference

Run `python scripts/zotero_cli.py --help` or a subcommand with `--help` for all options. The script uses only the Python standard library.
