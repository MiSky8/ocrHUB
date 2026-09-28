from fastapi.testclient import TestClient


def test_app_starts_and_serves_health_and_mcp_through_composed_lifespan():
    """Regression test for Task 15's lifespan composition (mounting the MCP
    sub-app's own TaskGroup-based lifespan into the outer app's lifespan).

    Using TestClient as a context manager triggers real ASGI lifespan
    startup/shutdown. This test exercises the actual `ocrhub.main` module
    (not just `api.py`'s create_app() in isolation), covering both /health
    and a real request through the /mcp mount and the module-level registry
    wiring.

    Without the lifespan composition, the MCP streamable-HTTP session
    manager's TaskGroup is never started, and any request to /mcp fails
    with `RuntimeError: Task group is not initialized. Make sure to use
    run().` (verified directly against ocrhub.main with the lifespan
    composition line removed, before writing this test) - a bare /health
    check alone would NOT catch that regression, since it never touches the
    MCP sub-app.

    Both requests are made against one TestClient/app instance in a single
    test because the MCP SDK's StreamableHTTPSessionManager.run() can only
    be entered once per process - a second `with TestClient(app)` block
    against the same module-level `app` raises "run() can only be called
    once per instance."
    """
    from ocrhub.main import app

    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    with TestClient(app) as client:
        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json() == {"status": "ok"}

        mcp_resp = client.post("/mcp/", json=init_request, headers=headers)
        assert mcp_resp.status_code == 200
        assert "mcp-session-id" in mcp_resp.headers
        assert '"protocolVersion"' in mcp_resp.text
