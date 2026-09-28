import httpx
import pytest

from ocrhub.adapters.ollama_adapter import OllamaAdapter


def test_available_false_when_no_host_configured(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert OllamaAdapter(host=None).available() is False


def test_available_false_when_host_unreachable():
    adapter = OllamaAdapter(host="http://localhost:1")  # nothing listens here
    assert adapter.available() is False


def test_available_true_when_host_responds(monkeypatch):
    adapter = OllamaAdapter(host="http://fake-ollama:11434")

    def fake_get(url, timeout):
        assert url == "http://fake-ollama:11434/api/tags"
        return httpx.Response(200, json={"models": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    assert adapter.available() is True


def test_extract_posts_image_and_parses_response(monkeypatch, sample_image_bytes):
    adapter = OllamaAdapter(host="http://fake-ollama:11434", model="deepseek-vl")

    def fake_post(url, json, timeout):
        assert url == "http://fake-ollama:11434/api/generate"
        assert json["model"] == "deepseek-vl"
        assert json["images"]
        return httpx.Response(200, json={"response": "OCRHUB TEST"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.ok is True
    assert result.text == "OCRHUB TEST"
