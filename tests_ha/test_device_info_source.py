"""The integration never treats a `DeviceInfo` as a mapping.

Home Assistant 2026.11 turned `DeviceInfo` into a dataclass and removes its
dict-style access in 2027.12. Core reports that access only from 2026.12, and on
older releases it is silent (they are plain dicts or an unreporting shim), so the
source is checked rather than the log.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PACKAGE = Path(__file__).parents[1] / "custom_components" / "unifi_gateway_rest"
_VENDORED = _PACKAGE / "aiounifigw"
_MAPPING_METHODS = {"copy", "get", "items", "keys", "pop", "setdefault", "update", "values"}
_ATTRIBUTES = {"device_info", "_attr_device_info"}


def _sources() -> dict[str, str]:
    return {
        str(path.relative_to(_PACKAGE)): path.read_text(encoding="utf-8")
        for path in sorted(_PACKAGE.rglob("*.py"))
        if _VENDORED not in path.parents
    }


def _name(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _mentions_device_info(annotation: ast.expr | None) -> bool:
    return annotation is not None and any(
        _name(node) == "DeviceInfo" for node in ast.walk(annotation) if isinstance(node, ast.expr)
    )


def dict_style_uses(sources: dict[str, str]) -> list[str]:
    """Return every place a value known to be a `DeviceInfo` is used as a mapping.

    Known means: built by `DeviceInfo(...)`, returned by a function annotated to
    return one, held in a name annotated or assigned as one, or read from a
    `device_info` / `_attr_device_info` attribute.
    """
    trees = {name: ast.parse(source) for name, source in sources.items()}
    builders = {"DeviceInfo"} | {
        node.name
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and _mentions_device_info(node.returns)
    }
    found: list[str] = []
    for filename, tree in trees.items():
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.arg) and _mentions_device_info(node.annotation):
                names.add(node.arg)
            elif isinstance(node, ast.AnnAssign) and _mentions_device_info(node.annotation):
                if target := _name(node.target):
                    names.add(target)
            elif (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and _name(node.value.func) in builders
            ):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))

        def is_info(node: ast.expr, names: set[str] = names) -> bool:
            if isinstance(node, ast.Call):
                return _name(node.func) in builders
            if isinstance(node, ast.Attribute):
                return node.attr in _ATTRIBUTES
            return isinstance(node, ast.Name) and node.id in names

        for node in ast.walk(tree):
            used: list[ast.expr] = []
            if isinstance(node, ast.Subscript):
                used = [node.value]
            elif isinstance(node, ast.Call):
                used = [k.value for k in node.keywords if k.arg is None]
                if isinstance(node.func, ast.Attribute) and node.func.attr in _MAPPING_METHODS:
                    used.append(node.func.value)
                if _name(node.func) == "dict":
                    used.extend(node.args)
            elif isinstance(node, ast.Dict):
                pairs = zip(node.keys, node.values, strict=True)
                used = [value for key, value in pairs if key is None]
            elif isinstance(node, ast.Compare):
                used = [
                    right
                    for op, right in zip(node.ops, node.comparators, strict=True)
                    if isinstance(op, ast.In | ast.NotIn)
                ]
            found.extend(f"{filename}:{value.lineno}" for value in used if is_info(value))
    return sorted(found)


def test_integration_never_uses_a_device_info_as_a_mapping() -> None:
    sources = _sources()
    assert "entity.py" in sources
    assert dict_style_uses(sources) == []


@pytest.mark.parametrize(
    "use",
    [
        "info = DeviceInfo()\ninfo['name']",
        "info = DeviceInfo()\ninfo['name'] = 'x'",
        "def f(info: DeviceInfo) -> None:\n    info['via_device_id'] = 'x'",
        "def build() -> DeviceInfo: ...\ncreate(**build())",
        "info: DeviceInfo\n{**info}",
        "info = DeviceInfo()\ndict(info)",
        "info = DeviceInfo()\n'name' in info",
        "self._attr_device_info.get('name')",
        "entity.device_info['name']",
        "info = DeviceInfo()\ninfo.copy()",
        "info = DeviceInfo()\ninfo.pop()",
        "info = DeviceInfo()\ninfo.setdefault()",
        "info = DeviceInfo()\ninfo.values()",
    ],
)
def test_guard_sees_each_dict_style_use(use: str) -> None:
    assert dict_style_uses({"sample.py": use})


def test_guard_allows_building_and_attribute_access() -> None:
    sample = (
        "fields: dict[str, Any] = {}\n"
        "info = DeviceInfo(**fields)\n"
        "info.name = 'x'\n"
        "create(**fields)\n"
        "fields['name']\n"
    )
    assert dict_style_uses({"sample.py": sample}) == []
