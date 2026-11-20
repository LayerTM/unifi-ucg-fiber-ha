"""Integration tests for the UniFi Gateway Home Assistant integration.

The tests import the harness as ``pytest_homeassistant``, the package Home
Assistant publishes from 2026.11. Older releases (the minimum leg) only have
``pytest_homeassistant_custom_component``, the same helpers under another name;
there every ``pytest_homeassistant[.x]`` import resolves to that module.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Sequence
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from types import ModuleType

_NAME = "pytest_homeassistant"
_LEGACY = "pytest_homeassistant_custom_component"


class _LegacyHarness(MetaPathFinder, Loader):
    """Serve ``pytest_homeassistant[.x]`` from the legacy package."""

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if fullname != _NAME and not fullname.startswith(f"{_NAME}."):
            return None
        legacy = importlib.util.find_spec(_LEGACY + fullname.removeprefix(_NAME))
        if legacy is None:
            return None
        return importlib.util.spec_from_loader(
            fullname, self, is_package=legacy.submodule_search_locations is not None
        )

    def create_module(self, spec: ModuleSpec) -> ModuleType:
        return importlib.import_module(_LEGACY + spec.name.removeprefix(_NAME))

    def exec_module(self, module: ModuleType) -> None:
        """Leave the legacy module as it is: it has already run."""


if importlib.util.find_spec(_NAME) is None:
    sys.meta_path.append(_LegacyHarness())
