"""Phase 1 smoke test — package imports and version is exposed."""

from __future__ import annotations

import agent_gateway


def test_package_version_present() -> None:
    assert agent_gateway.__version__
    assert agent_gateway.__version__.count(".") == 2
