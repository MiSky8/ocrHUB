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


def test_index_page_has_dashboard_elements(tmp_path):
    client = TestClient(create_app(build_registry(), ResultStore(tmp_path)))
    resp = client.get("/")

    assert resp.status_code == 200
    assert 'id="run-all-btn"' in resp.text
    assert 'id="file-input"' in resp.text
    assert 'id="results-grid"' in resp.text


def test_dashboard_css_is_served(tmp_path):
    client = TestClient(create_app(build_registry(), ResultStore(tmp_path)))
    resp = client.get("/static/dashboard.css")

    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]
