from ocrhub.adapters.base import OcrAdapter


class EngineRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, OcrAdapter] = {}

    def register(self, adapter: OcrAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def available_engines(self) -> list[str]:
        return [name for name, adapter in self._adapters.items() if adapter.available()]

    def get(self, name: str) -> OcrAdapter:
        return self._adapters[name]

    def all(self) -> list[OcrAdapter]:
        return list(self._adapters.values())
