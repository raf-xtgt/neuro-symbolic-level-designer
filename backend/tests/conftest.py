"""
Test setup. LLM calls replay recorded fixtures (tests/llm_fixtures/) unless
LLM_MODE is set; tests marked ``live`` need the network and run only with
``LLM_MODE=live``.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("LLM_MODE", "replay")
# dart analyze of generated code takes seconds per job; its own tests turn it on.
os.environ.setdefault("DART_ANALYZE", "off")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls the real LLM; runs only with LLM_MODE=live")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("LLM_MODE") == "live":
        return
    skip = pytest.mark.skip(reason="needs the network; set LLM_MODE=live to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
