from fastapi.testclient import TestClient

from ocrhub.api import build_registry, create_app


def test_index_page_loads():
    client = TestClient(create_app(build_registry()))
    resp = client.get("/")

    assert resp.status_code == 200
    assert "ocrHub" in resp.text
    assert 'id="engine-list"' in resp.text


def test_static_app_js_is_served():
    client = TestClient(create_app(build_registry()))
    resp = client.get("/static/app.js")

    assert resp.status_code == 200
    assert "text/javascript" in resp.headers["content-type"]
