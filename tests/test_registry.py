import pytest

from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry


class FakeAdapter:
    def __init__(self, name: str, is_available: bool):
        self.name = name
        self._is_available = is_available

    def available(self) -> bool:
        return self._is_available

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        return OcrResult(engine=self.name, text="fake", elapsed_ms=1)


def test_available_engines_only_lists_available_adapters():
    registry = EngineRegistry()
    registry.register(FakeAdapter("on", is_available=True))
    registry.register(FakeAdapter("off", is_available=False))

    assert registry.available_engines() == ["on"]


def test_get_returns_registered_adapter():
    registry = EngineRegistry()
    adapter = FakeAdapter("on", is_available=True)
    registry.register(adapter)

    assert registry.get("on") is adapter


def test_get_unknown_engine_raises_key_error():
    registry = EngineRegistry()
    with pytest.raises(KeyError):
        registry.get("nope")
