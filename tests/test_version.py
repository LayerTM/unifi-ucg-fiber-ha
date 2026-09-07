"""The release version is stated once, in the package, and read from there."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import aiounifigw

ROOT = Path(__file__).resolve().parents[1]
SOURCE_OF_TRUTH = "src/aiounifigw/__init__.py"


def _pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_pyproject_derives_the_version_instead_of_repeating_it() -> None:
    data = _pyproject()
    project = data["project"]
    assert isinstance(project, dict)
    assert "version" not in project, "a second literal version can drift from the first"
    assert "version" in project.get("dynamic", [])

    tool = data["tool"]
    assert isinstance(tool, dict)
    assert tool["hatch"]["version"]["path"] == SOURCE_OF_TRUTH


def test_integration_manifest_names_the_same_release() -> None:
    manifest = ROOT / "custom_components" / "unifi_gateway_rest" / "manifest.json"
    with manifest.open(encoding="utf-8") as handle:
        assert json.load(handle)["version"] == aiounifigw.__version__
