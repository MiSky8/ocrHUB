import base64

from mcp.server.mcpserver import MCPServer

from ocrhub.registry import EngineRegistry
from ocrhub.service import process_document


def build_mcp_server(registry: EngineRegistry) -> MCPServer:
    mcp = MCPServer("ocrhub")

    @mcp.tool()
    def ocr_document(file_base64: str, filename: str, engines: list[str]) -> dict:
        """Run one or more OCR engines over a base64-encoded document and return normalized results."""
        file_bytes = base64.b64decode(file_base64)
        results = process_document(registry, file_bytes, filename, engines)
        return {"results": [vars(r) | {"pages": [vars(p) for p in r.pages]} for r in results]}

    return mcp


def mcp_asgi_app(registry: EngineRegistry):
    return build_mcp_server(registry).streamable_http_app()
