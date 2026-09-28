import base64
import json

import pytest

from ocrhub.mcp_server import build_mcp_server
from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry


class StubAdapter:
    name = "stub"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        assert file_bytes == b"hello"
        return OcrResult(engine=self.name, text="stub text", elapsed_ms=1)


@pytest.mark.asyncio
async def test_ocr_document_tool_decodes_and_runs_engine():
    registry = EngineRegistry()
    registry.register(StubAdapter())
    server = build_mcp_server(registry)

    call_result = await server.call_tool(
        "ocr_document",
        {
            "file_base64": base64.b64encode(b"hello").decode("ascii"),
            "filename": "f.png",
            "engines": ["stub"],
        },
    )

    assert call_result.is_error is False
    result = json.loads(call_result.content[0].text)

    assert result["results"][0]["engine"] == "stub"
    assert result["results"][0]["text"] == "stub text"
