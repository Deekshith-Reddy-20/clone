"""Skip legacy fast-path unittest modules unless RUN_LEGACY_FASTPATH=1."""

from __future__ import annotations

import os
import unittest

SKIP_REASON = "legacy fast-path; set RUN_LEGACY_FASTPATH=1 or pytest -m legacy"


def skip_unless_legacy(cls: type) -> type:
    if os.getenv("RUN_LEGACY_FASTPATH") == "1":
        return cls
    return unittest.skip(SKIP_REASON)(cls)