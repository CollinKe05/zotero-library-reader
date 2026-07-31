#!/usr/bin/env python3
"""Source-tree entry point for the Zotero Local Reader CLI."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from zotero_local_reader.backend import main


if __name__ == "__main__":
    main()
