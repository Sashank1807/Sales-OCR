#!/usr/bin/env python3
"""Convenience runner and API for benchmarks.

Full implementation lives in `benchmarks/benchmark.py`.
See `benchmarks/README.md` for details.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "benchmarks") not in sys.path:
    sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.benchmark import *
from benchmarks.benchmark import main

if __name__ == "__main__":
    sys.exit(main())
