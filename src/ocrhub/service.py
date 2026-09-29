from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry
from ocrhub.storage import ResultStore, content_hash


def process_document(
    registry: EngineRegistry,
    file_bytes: bytes,
    filename: str,
    engine_names: list[str],
    store: ResultStore | None = None,
    refresh: bool = False,
) -> list[OcrResult]:
    results: list[OcrResult] = []
    available = set(registry.available_engines())

    hash_id = None
    if store is not None:
        hash_id = content_hash(file_bytes)
        store.save_input(hash_id, filename, file_bytes)

    for name in engine_names:
        if name not in available:
            results.append(OcrResult(engine=name, text="", error="engine not available"))
            continue

        if hash_id is not None and not refresh:
            cached = store.get(hash_id, name)
            if cached is not None:
                results.append(cached)
                continue

        adapter = registry.get(name)
        try:
            result = adapter.extract(file_bytes, filename)
        except Exception as exc:  # noqa: BLE001 - per-engine isolation is the point
            result = OcrResult(engine=name, text="", error=str(exc))

        if hash_id is not None and result.ok:
            store.save(hash_id, name, result)

        results.append(result)

    return results
