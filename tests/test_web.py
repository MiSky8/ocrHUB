from fastapi.testclient import TestClient

from ocrhub.api import build_registry, create_app
from ocrhub.storage import ResultStore


def test_index_page_loads(tmp_path):
    client = TestClient(create_app(build_registry(), ResultStore(tmp_path)))
    resp = client.get("/")

    assert resp.status_code == 200
    assert "ocrHub" in resp.text
    assert 'id="engine-list"' in resp.text


def test_static_app_js_is_served(tmp_path):
    client = TestClient(create_app(build_registry(), ResultStore(tmp_path)))
    resp = client.get("/static/app.js")

    assert resp.status_code == 200
    assert "text/javascript" in resp.headers["content-type"]
