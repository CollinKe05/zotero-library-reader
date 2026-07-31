# Upstream integrations and capability routing

Use this reference to decide whether the native skill is sufficient or a
separate upstream project is a better fit.

## Native default: Zotero Library Reader

Choose the native skill for:

- zero-dependency local CLI access;
- personal and group collection discovery;
- validated SQLite snapshots that include the current database state;
- metadata, attachment paths, cached full text, notes, and annotations;
- read-only MCP access;
- Codex/PDF research workflows and optional Obsidian export.

It does not require Zotero to be running, a Zotero cloud key, or the local API
on port 23119. Only optional Scite enrichment uses the network.

## 54yyyu/zotero-mcp

Repository: <https://github.com/54yyyu/zotero-mcp>

Use it separately when the user explicitly needs:

- vector semantic search with ChromaDB and embedding models;
- broad Zotero local-API or Web-API coverage;
- annotation/note creation and other write operations;
- item import, duplicate management, or collection mutation.

It is the broader general-purpose MCP project and is MIT licensed, but its
full feature set has substantially more dependencies. Semantic extras can
download large model/index components, and local-API workflows generally
require Zotero to be running with the API enabled. Do not install those extras
automatically; ask when their disk, network, and write implications matter.

## scitedotai/scite-zotero-plugin

Repository: <https://github.com/scitedotai/scite-zotero-plugin>

Choose the plugin when users primarily want Scite supporting, contrasting, and
mentioning columns directly inside Zotero. The repository currently does not
declare a software license, so do not copy its source into this MIT project.
This skill independently calls the public Scite endpoints for optional
read-only DOI enrichment.

## MuiseDestiny/zotero-gpt

Repository: <https://github.com/MuiseDestiny/zotero-gpt>

Choose it separately when users want an in-Zotero chat panel and interactive
commands over the current PDF or selection. It is AGPL-3.0 licensed and
overlaps with capabilities already supplied by Codex, so do not merge its code
into this MIT skill. Treat custom executable command tags and model/API
configuration as a larger security and maintenance surface.

## Composition rule

Prefer composition over bundling:

- native skill = safe local access and research-workflow substrate;
- `zotero-mcp` = optional broad/semantic/write companion;
- Scite plugin = optional in-Zotero citation UI;
- Zotero-GPT = optional in-Zotero conversational UI.

Never imply that installing one project automatically installs or configures
the others.
