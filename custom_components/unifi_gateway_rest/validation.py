"""The schema engine the flows build their forms with.

Home Assistant 2026.10 validates with probatio, a voluptuous-compatible engine,
and aliases ``voluptuous`` to it in ``sys.modules`` at startup. Older cores still
run voluptuous itself. Importing ``voluptuous`` therefore yields whichever engine
the running core uses, and the type checker, which runs against the newest core,
is told the engine that core actually runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import probatio as vol
else:
    import voluptuous as vol

__all__ = ["vol"]
