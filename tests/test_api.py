import io

from fastapi.testclient import TestClient

from ocrhub.api import build_registry, create_app
from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry
from ocrhub.storage import ResultStore


class StubAdapter:
    name = "stub"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        return OcrResult(engine=self.name, text="stub text", elapsed_ms=1)


class FailingStubAdapter:
    name = "failing-stub"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        return OcrResult(engine=self.name, text="", elapsed_ms=1, error="boom")


def _client(tmp_path) -> TestClient:
    registry = EngineRegistry()
    registry.register(StubAdapter())
    return TestClient(create_app(registry, ResultStore(tmp_path)))


def _failing_client(tmp_path) -> TestClient:
    registry = EngineRegistry()
    registry.register(FailingStubAdapter())
    return TestClient(create_app(registry, ResultStore(tmp_path)))


def test_health(tmp_path):
    resp = _client(tmp_path).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_engines_lists_available_only(tmp_path):
    resp = _client(tmp_path).get("/engines")
    assert resp.status_code == 200
    assert resp.json() == {"engines": ["stub"]}


def test_ocr_runs_requested_engine(tmp_path):
    client = _client(tmp_path)
    files = {"file": ("f.png", io.BytesIO(b"fake-bytes"), "image/png")}
    resp = client.post("/ocr", files=files, data={"engines": ["stub"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["engine"] == "stub"
    assert body["results"][0]["text"] == "stub text"
    assert body["results"][0]["ok"] is True


def test_ocr_reports_ok_false_for_failing_engine(tmp_path):
    client = _failing_client(tmp_path)
    files = {"file": ("f.png", io.BytesIO(b"fake-bytes"), "image/png")}
    resp = client.post("/ocr", files=files, data={"engines": ["failing-stub"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["ok"] is False
    assert body["results"][0]["error"] == "boom"


def test_ocr_requires_at_least_one_engine(tmp_path):
    client = _client(tmp_path)
    files = {"file": ("f.png", io.BytesIO(b"fake-bytes"), "image/png")}
    resp = client.post("/ocr", files=files, data={})

    assert resp.status_code == 400


def test_build_registry_registers_all_six_engines():
    registry = build_registry()
    names = {adapter.name for adapter in registry.all()}
    assert names == {
        "pdfplumber",
        "tesseract",
        "surya",
        "paddleocr",
        "ollama-deepseek",
        "datalab",
    }
