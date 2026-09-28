import io

from fastapi.testclient import TestClient

from ocrhub.api import build_registry, create_app
from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry


class StubAdapter:
    name = "stub"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        return OcrResult(engine=self.name, text="stub text", elapsed_ms=1)


def _client() -> TestClient:
    registry = EngineRegistry()
    registry.register(StubAdapter())
    return TestClient(create_app(registry))


def test_health():
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_engines_lists_available_only():
    resp = _client().get("/engines")
    assert resp.status_code == 200
    assert resp.json() == {"engines": ["stub"]}


def test_ocr_runs_requested_engine():
    client = _client()
    files = {"file": ("f.png", io.BytesIO(b"fake-bytes"), "image/png")}
    resp = client.post("/ocr", files=files, data={"engines": ["stub"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["engine"] == "stub"
    assert body["results"][0]["text"] == "stub text"


def test_ocr_requires_at_least_one_engine():
    client = _client()
    files = {"file": ("f.png", io.BytesIO(b"fake-bytes"), "image/png")}
    resp = client.post("/ocr", files=files, data={})

    assert resp.status_code == 400


def test_build_registry_registers_all_five_engines():
    registry = build_registry()
    names = {adapter.name for adapter in registry.all()}
    assert names == {"pdfplumber", "tesseract", "surya", "paddleocr", "ollama-deepseek"}
