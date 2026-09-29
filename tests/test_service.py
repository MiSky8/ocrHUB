from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry
from ocrhub.service import process_document
from ocrhub.storage import ResultStore, content_hash


class WorkingAdapter:
    name = "working"

    def __init__(self):
        self.calls = 0

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        self.calls += 1
        return OcrResult(engine=self.name, text="ok", elapsed_ms=1)


class BrokenAdapter:
    name = "broken"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        raise RuntimeError("model crashed")


def _registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(WorkingAdapter())
    registry.register(BrokenAdapter())
    return registry


def test_process_document_returns_results_in_requested_order():
    results = process_document(_registry(), b"bytes", "f.png", ["working", "broken"])
    assert [r.engine for r in results] == ["working", "broken"]


def test_process_document_captures_adapter_exception_as_error():
    results = process_document(_registry(), b"bytes", "f.png", ["broken"])
    assert results[0].ok is False
    assert "model crashed" in results[0].error


def test_process_document_marks_unregistered_engine_unavailable():
    results = process_document(_registry(), b"bytes", "f.png", ["missing"])
    assert results[0].ok is False
    assert results[0].error == "engine not available"


def test_process_document_one_failure_does_not_block_others():
    results = process_document(_registry(), b"bytes", "f.png", ["broken", "working"])
    by_engine = {r.engine: r for r in results}
    assert by_engine["broken"].ok is False
    assert by_engine["working"].ok is True


def test_process_document_with_store_calls_adapter_once_then_uses_cache(tmp_path):
    registry = EngineRegistry()
    adapter = WorkingAdapter()
    registry.register(adapter)
    store = ResultStore(tmp_path)

    first = process_document(registry, b"bytes", "f.png", ["working"], store=store)
    second = process_document(registry, b"bytes", "f.png", ["working"], store=store)

    assert adapter.calls == 1
    assert first[0].text == second[0].text == "ok"


def test_process_document_with_store_and_refresh_recomputes(tmp_path):
    registry = EngineRegistry()
    adapter = WorkingAdapter()
    registry.register(adapter)
    store = ResultStore(tmp_path)

    process_document(registry, b"bytes", "f.png", ["working"], store=store)
    process_document(registry, b"bytes", "f.png", ["working"], store=store, refresh=True)

    assert adapter.calls == 2


def test_process_document_does_not_cache_failed_results(tmp_path):
    registry = EngineRegistry()
    registry.register(BrokenAdapter())
    store = ResultStore(tmp_path)

    process_document(registry, b"bytes", "f.png", ["broken"], store=store)
    cached = store.get(content_hash(b"bytes"), "broken")

    assert cached is None


def test_process_document_with_store_saves_input_file(tmp_path):
    registry = EngineRegistry()
    registry.register(WorkingAdapter())
    store = ResultStore(tmp_path)

    process_document(registry, b"bytes", "f.png", ["working"], store=store)

    saved = list((tmp_path / "input").glob("*-f.png"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"bytes"
