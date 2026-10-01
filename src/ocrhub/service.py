import logging

from ocrhub.models import OcrResult
from ocrhub.pdf_utils import normalize_image
from ocrhub.registry import EngineRegistry
from ocrhub.storage import ResultStore, content_hash


logger = logging.getLogger(__name__)


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

    # Saving is a convenience, not part of the job: if the data folder can't be
    # written (typically a Linux bind mount owned by another user), the OCR
    # result must still be returned, just not saved or cached.
    hash_id = None
    if store is not None:
        hash_id = content_hash(file_bytes)
        try:
            store.save_input(hash_id, filename, file_bytes)
        except OSError as exc:
            logger.warning("Could not save the uploaded file, results will not be saved: %s", exc)
            hash_id = None

    # The original is stored as uploaded; engines get the normalised copy.
    engine_bytes, engine_filename = normalize_image(file_bytes, filename)

    for name in engine_names:
        if name not in available:
            results.append(OcrResult(engine=name, text="", error="engine not available"))
            continue

        if hash_id is not None and not refresh:
            try:
                cached = store.get(hash_id, name)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.warning("Ignoring unreadable saved %s result: %s", name, exc)
                cached = None
            if cached is not None:
                results.append(cached)
                continue

        adapter = registry.get(name)
        try:
            result = adapter.extract(engine_bytes, engine_filename)
        except Exception as exc:  # noqa: BLE001 - per-engine isolation is the point
            result = OcrResult(engine=name, text="", error=str(exc))

        if hash_id is not None and result.ok:
            try:
                store.save(hash_id, name, result)
            except OSError as exc:
                logger.warning("Could not save the %s result: %s", name, exc)

        results.append(result)

    return results
