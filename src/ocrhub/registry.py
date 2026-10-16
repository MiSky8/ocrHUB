from ocrhub.adapters.base import OcrAdapter


class EngineRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, OcrAdapter] = {}

    def register(self, adapter: OcrAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def available_engines(self) -> list[str]:
        available = []
        for name, adapter in self._adapters.items():
            try:
                if adapter.available():
                    available.append(name)
            except Exception:  # noqa: BLE001 - per-engine isolation is the point
                continue
        return available

    def capabilities(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for name in self.available_engines():
            method = getattr(self._adapters[name], "capabilities", None)
            try:
                result[name] = list(method()) if method else []
            except Exception:  # noqa: BLE001 - one adapter must not break /engines
                result[name] = []
        return result

    def get(self, name: str) -> OcrAdapter:
        return self._adapters[name]

    def all(self) -> list[OcrAdapter]:
        return list(self._adapters.values())
