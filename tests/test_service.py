from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry
from ocrhub.service import process_document


class WorkingAdapter:
    name = "working"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
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
