#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10,<3.15"
# dependencies = [
#   "tree-sitter>=0.25,<0.27",
#   "tree-sitter-c==0.24.2",
#   "clang-format==23.1.5",
# ]
# [tool.uv]
# exclude-newer = "2026-11-11T00:00:00Z"
# ///
"""The readable-c tool. Run it with `uv run`, which installs its dependencies:

uv run <skill-folder>/scripts/readable_c.py --help
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from readablec.cli import main

if __name__ == "__main__":
    sys.exit(main())
