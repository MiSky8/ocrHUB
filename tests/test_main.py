from fastapi.testclient import TestClient


def test_app_starts_and_serves_health_through_full_lifespan():
    """Regression test for Task 15's lifespan composition (mounting the MCP
    sub-app's own TaskGroup-based lifespan into the outer app's lifespan).

    Using TestClient as a context manager triggers real ASGI lifespan
    startup/shutdown. If the MCP sub-app's lifespan were not composed
    correctly, mounting /mcp would fail requests with "Task group is not
    initialized. Make sure to use run()." This test exercises the actual
    `ocrhub.main` module (not just `api.py`'s create_app() in isolation) so
    it also covers the /mcp mount and the module-level registry wiring.
    """
    from ocrhub.main import app

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
