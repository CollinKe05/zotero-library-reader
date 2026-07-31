# PDF explanation and library synthesis

Read this reference when the user asks to explain a paper PDF, compare papers, analyze an entire collection, create a research map, or export an Obsidian network.

## Single-paper explanation

1. Resolve the item or attachment with `item` or `attachment`.
2. Run `fulltext --key <key>` first. If Zotero has a complete cached text,
   use it for efficient first-pass reading; otherwise read the resolved PDF
   with the available PDF workflow.
3. Retrieve the relevant collection's `digest` when the user's own notes or
   highlights may affect interpretation.
4. Separate:
   - research question and motivation;
   - central method and system pipeline;
   - data, embodiment, observations, actions, and supervision;
   - experiments, baselines, metrics, and main quantitative results;
   - ablations and failure modes;
   - limitations, assumptions, and reusable ideas.
5. Ground technical claims in the PDF. Mark interpretation or inference explicitly.
6. Relate the paper to neighboring items from the same Zotero collection when useful.

## Collection-wide synthesis

1. Run `bundle` or MCP `zotero_get_collection_bundle`.
2. Run `digest` to preserve the user's notes and PDF highlights as a separate
   evidence layer.
3. Use abstracts and cached full text for a first-pass taxonomy; inspect PDFs
   for claims that matter to the requested synthesis.
4. Build one evidence row per paper before writing cross-paper conclusions.
5. Connect papers along useful axes:
   - chronology and intellectual lineage;
   - task and embodiment;
   - perception/language/action representation;
   - policy architecture and action generation;
   - training data and supervision;
   - generalization setting;
   - evaluation protocol;
   - strengths, limitations, and unresolved gaps.
6. Do not infer direct citation or influence from collection membership alone.
7. Distinguish metadata links, explicit citations, and semantic relationships.
8. Use `scite --collection` only when citation tallies or editorial notices
   materially help. Treat them as screening signals, not conclusions.

## Obsidian export

Only export when the user explicitly asks.

Use:

`python scripts/zotero_cli.py obsidian --collection "Research/Robotics" --output-dir "<target>"`

This creates metadata notes, collection/creator nodes, `00-Index.md`, and `graph.json`.
For a semantic paper-to-paper network, first read the relevant PDFs and create a JSON array:

```json
[
  {
    "source": "SOURCE_ZOTERO_KEY",
    "target": "TARGET_ZOTERO_KEY",
    "relation": "extends",
    "explanation": "Evidence-grounded explanation"
  }
]
```

Pass it with `--relations`. Never label an inferred relationship as an explicit citation.
