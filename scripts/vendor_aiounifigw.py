#!/usr/bin/env python3
"""Vendor the aiounifigw client into the integration so it ships with HACS.

`src/aiounifigw` is the source of truth. This copies it into the integration
package as `custom_components/unifi_gateway_rest/aiounifigw/`, so the integration
has no external (PyPI) dependency — Home Assistant already ships aiohttp + yarl.

CI runs this and fails if the vendored copy has drifted from the source
(`git diff --exit-code` after running it).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "aiounifigw"
DST = ROOT / "custom_components" / "unifi_gateway_rest" / "aiounifigw"


def main() -> int:
    if not SRC.is_dir():
        print(f"source not found: {SRC}", file=sys.stderr)
        return 1
    if DST.exists():
        shutil.rmtree(DST)
    # cli.py / mcp / summary bring in (or exist only for) the optional cli/mcp
    # extras the HA integration must not require — exclude them from the vendored
    # copy (present only in the src package).
    shutil.copytree(
        SRC,
        DST,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "cli.py", "mcp*", "summary.py"),
    )
    print(f"vendored {SRC} -> {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
