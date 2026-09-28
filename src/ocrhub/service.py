from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry


def process_document(
    registry: EngineRegistry,
    file_bytes: bytes,
    filename: str,
    engine_names: list[str],
) -> list[OcrResult]:
    results: list[OcrResult] = []
    available = set(registry.available_engines())

    for name in engine_names:
        if name not in available:
            results.append(OcrResult(engine=name, text="", error="engine not available"))
            continue

        adapter = registry.get(name)
        try:
            results.append(adapter.extract(file_bytes, filename))
        except Exception as exc:  # noqa: BLE001 - per-engine isolation is the point
            results.append(OcrResult(engine=name, text="", error=str(exc)))

    return results
