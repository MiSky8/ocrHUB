import json

from ocrhub.models import BoxResult, OcrResult, PageResult
from ocrhub.storage import ResultStore, content_hash


def test_content_hash_is_stable_and_12_hex_chars():
    h1 = content_hash(b"hello world")
    h2 = content_hash(b"hello world")
    assert h1 == h2
    assert len(h1) == 12
    assert all(c in "0123456789abcdef" for c in h1)


def test_content_hash_differs_for_different_bytes():
    assert content_hash(b"a") != content_hash(b"b")


def test_get_returns_none_when_nothing_cached(tmp_path):
    store = ResultStore(tmp_path)
    assert store.get("deadbeef0000", "tesseract") is None


def test_save_then_get_roundtrips_full_result(tmp_path):
    store = ResultStore(tmp_path)
    result = OcrResult(
        engine="tesseract",
        text="hello\nworld",
        pages=[
            PageResult(
                page_number=1,
                text="hello\nworld",
                confidence=0.9,
                boxes=[
                    BoxResult(text="hello", x0=1, y0=2, x1=3, y1=4, confidence=0.9),
                    BoxResult(text="world", x0=5, y0=6, x1=7, y1=8, reading_order=1, region_type="Text"),
                ],
                image_base64="Zm9v",
            )
        ],
        confidence=0.9,
        elapsed_ms=42,
    )

    store.save("deadbeef0000", "tesseract", result)
    loaded = store.get("deadbeef0000", "tesseract")

    assert loaded == result


def test_save_input_writes_file_once_and_meta(tmp_path):
    store = ResultStore(tmp_path)
    store.save_input("deadbeef0000", "sample.png", b"file-bytes")

    saved = list((tmp_path / "input").glob("deadbeef0000-*"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"file-bytes"

    meta_path = tmp_path / "output" / "deadbeef0000" / "_meta.json"
    meta = json.loads(meta_path.read_text())
    assert meta["filename"] == "sample.png"
    assert "saved_at" in meta


def test_save_input_is_idempotent(tmp_path):
    store = ResultStore(tmp_path)
    store.save_input("deadbeef0000", "sample.png", b"file-bytes")
    store.save_input("deadbeef0000", "sample.png", b"file-bytes")

    saved = list((tmp_path / "input").glob("deadbeef0000-*"))
    assert len(saved) == 1


def test_raw_engine_response_survives_save_and_load(tmp_path):
    from ocrhub.models import OcrResult
    from ocrhub.storage import ResultStore

    store = ResultStore(tmp_path)
    store.save("abc", "datalab", OcrResult(engine="datalab", text="x", raw={"children": []}))

    assert store.get("abc", "datalab").raw == {"children": []}
