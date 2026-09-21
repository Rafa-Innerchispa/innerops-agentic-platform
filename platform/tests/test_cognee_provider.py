from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
PROVIDER_PATH = PLATFORM_ROOT / "raphiia_openai" / "cognee_provider.py"


class FakeCognee:
    def __init__(self):
        self.served = None
        self.remembered = []

    async def serve(self, url, api_key):
        self.served = (url, api_key)

    async def recall(self, query, **kwargs):
        return [
            SimpleNamespace(
                text="remembered fact",
                metadata={"kind": "test"},
                source="graph",
                search_type="GRAPH_COMPLETION",
                dataset_name=kwargs.get("datasets", [""])[0],
            )
        ]

    async def remember(self, data, **kwargs):
        self.remembered.append((data, kwargs))
        return SimpleNamespace(status="stored")


def load_provider():
    spec = importlib.util.spec_from_file_location("cognee_provider_under_test", PROVIDER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def provider(monkeypatch):
    fake = FakeCognee()
    monkeypatch.setitem(sys.modules, "cognee", fake)
    monkeypatch.setenv("COGNEE_SERVICE_URL", "https://tenant.example.cognee.ai")
    monkeypatch.setenv("COGNEE_API_KEY", "test-key")
    monkeypatch.setenv("COGNEE_DATASET", "personal-brain-test")
    return load_provider(), fake


def test_status_redacts_secret(provider):
    module, _ = provider
    result = asyncio.run(module.status())
    assert result["ok"] is True
    assert result["credential_present"] is True
    assert "test-key" not in str(result)


def test_memory_search_uses_cloud_and_dataset(provider):
    module, fake = provider
    result = asyncio.run(module.memory_search("What matters?", limit=3))
    assert result["ok"] is True
    assert result["dataset"] == "personal-brain-test"
    assert result["results"][0]["text"] == "remembered fact"
    assert fake.served == ("https://tenant.example.cognee.ai", "test-key")


def test_remember_never_returns_credential(provider):
    module, fake = provider
    result = asyncio.run(
        module.remember("A verified outcome", metadata={"source": "test"})
    )
    assert result["ok"] is True
    assert fake.remembered
    assert "test-key" not in str(result)
