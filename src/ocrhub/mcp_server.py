import base64

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from ocrhub.registry import EngineRegistry
from ocrhub.service import process_document


def build_mcp_server(registry: EngineRegistry) -> MCPServer:
    mcp = MCPServer("ocrhub")

    @mcp.tool()
    def ocr_document(file_base64: str, filename: str, engines: list[str]) -> dict:
        """Run one or more OCR engines over a base64-encoded document and return normalized results."""
        file_bytes = base64.b64decode(file_base64)
        results = process_document(registry, file_bytes, filename, engines)
        return {
            "results": [
                vars(r)
                | {
                    "pages": [
                        vars(p) | {"boxes": None, "image_base64": None} for p in r.pages
                    ]
                }
                for r in results
            ]
        }

    return mcp


def mcp_asgi_app(registry: EngineRegistry):
    # streamable_http_path="/": the app is mounted at "/mcp" by main.py, and the
    # SDK's own default path is also "/mcp", which would otherwise stack into
    # "/mcp/mcp". Serving at the sub-app's root makes the mounted path exactly
    # "/mcp" as intended.
    #
    # transport_security: the SDK auto-enables Host-header DNS-rebinding
    # protection restricted to loopback hosts (127.0.0.1/localhost/::1)
    # whenever `host` is left at its loopback default. ocrHub's server binds
    # 0.0.0.0 for Docker/LAN deployment, so that protection would reject every
    # legitimate request (container hostnames, LAN IPs, etc.) with 421.
    # DNS-rebinding protection guards a browser-facing service that is only
    # ever meant to be reached via loopback from local JS; it doesn't fit a
    # server intentionally exposed beyond loopback, where isolation instead
    # comes from the network boundary (Docker network / reverse proxy).
    # Disabling it here matches the SDK's own designed default for any
    # non-loopback deployment (see TransportSecurityMiddleware.__init__,
    # which disables protection "by default for backwards compatibility"
    # when no settings are supplied) rather than opening a new hole.
    return build_mcp_server(registry).streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
