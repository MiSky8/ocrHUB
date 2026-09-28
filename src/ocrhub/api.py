from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from ocrhub.adapters.ollama_adapter import OllamaAdapter
from ocrhub.adapters.paddleocr_adapter import PaddleOcrAdapter
from ocrhub.adapters.pdfplumber_adapter import PdfplumberAdapter
from ocrhub.adapters.surya_adapter import SuryaAdapter
from ocrhub.adapters.tesseract_adapter import TesseractAdapter
from ocrhub.registry import EngineRegistry
from ocrhub.service import process_document


def build_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(PdfplumberAdapter())
    registry.register(TesseractAdapter())
    registry.register(SuryaAdapter())
    registry.register(PaddleOcrAdapter())
    registry.register(OllamaAdapter())
    return registry


def create_app(registry: EngineRegistry | None = None) -> FastAPI:
    registry = registry or build_registry()
    app = FastAPI(title="ocrHub")
    app.state.registry = registry

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/engines")
    def engines() -> dict:
        return {"engines": registry.available_engines()}

    @app.post("/ocr")
    async def ocr(file: UploadFile = File(...), engines: list[str] = Form(default=[])) -> dict:
        if not engines:
            raise HTTPException(status_code=400, detail="at least one engine is required")

        file_bytes = await file.read()
        results = process_document(registry, file_bytes, file.filename or "upload", engines)
        return {"results": [vars(r) | {"pages": [vars(p) for p in r.pages]} for r in results]}

    return app
