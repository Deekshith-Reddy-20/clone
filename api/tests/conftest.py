"""Pytest markers and legacy fast-path policy."""

from __future__ import annotations

import os

import pytest

LEGACY_FASTPATH_MODULES = (
    "test_live_call_transcript",
    "test_vforms_booking_dialogue",
    "test_reception_grounded",
    "test_post_booking_smalltalk",
    "test_pool_faq_conversation",
    "test_resort_booking_regression",
    "test_booking_loop_regression",
    "test_conversation_sim",
    "test_live_voice_benchmark",
    "test_hospital_reception_regression",
    "test_vfarms_reception_transcript",
    "test_employee_playbook",
)

# Documented in docs/legacy-fastpath-tests.md


def pytest_configure(config: pytest.Config) -> None:
    os.environ.setdefault("KARYUK_VOICE_LLM_FIRST", "1")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    legacy_selected = config.option.markexpr and "legacy" in config.option.markexpr
    for item in items:
        mod = item.module.__name__.split(".")[-1]
        if mod in LEGACY_FASTPATH_MODULES and not legacy_selected:
            item.add_marker(pytest.mark.legacy)
            if "legacy" not in config.option.markexpr and "live_llm" not in (config.option.markexpr or ""):
                item.add_marker(
                    pytest.mark.skip(reason="legacy fast-path; run pytest -m legacy after Phase E cleanup")
                )