import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ocrhub.models import BoxResult, OcrResult, PageResult


def content_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()[:12]


def _result_from_dict(data: dict) -> OcrResult:
    pages = [
        PageResult(
            page_number=p["page_number"],
            text=p["text"],
            confidence=p.get("confidence"),
            boxes=[BoxResult(**b) for b in p.get("boxes", [])],
            image_base64=p.get("image_base64"),
            width=p.get("width"),
            height=p.get("height"),
        )
        for p in data.get("pages", [])
    ]
    return OcrResult(
        engine=data["engine"],
        text=data["text"],
        pages=pages,
        confidence=data.get("confidence"),
        elapsed_ms=data.get("elapsed_ms", 0),
        error=data.get("error"),
        raw=data.get("raw"),
    )


class ResultStore:
    """Persists uploaded files and per-engine OCR results to disk, keyed by
    the content hash of the uploaded file so identical files are cached
    (and never re-run) regardless of what they're named."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.input_dir = self.root / "input"
        self.output_dir = self.root / "output"

    def get(self, hash_id: str, engine: str) -> OcrResult | None:
        path = self.output_dir / hash_id / f"{engine}.json"
        if not path.exists():
            return None
        return _result_from_dict(json.loads(path.read_text()))

    def save(self, hash_id: str, engine: str, result: OcrResult) -> None:
        out_dir = self.output_dir / hash_id
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{engine}.json"
        path.write_text(json.dumps(asdict(result), indent=2))

    def save_input(self, hash_id: str, filename: str, file_bytes: bytes) -> None:
        self.input_dir.mkdir(parents=True, exist_ok=True)
        safe_name = filename.replace("/", "_") if filename else "upload"
        path = self.input_dir / f"{hash_id}-{safe_name}"
        if not path.exists():
            path.write_bytes(file_bytes)

        meta_dir = self.output_dir / hash_id
        meta_dir.mkdir(parents=True, exist_ok=True)
        meta_path = meta_dir / "_meta.json"
        if not meta_path.exists():
            meta_path.write_text(
                json.dumps(
                    {"filename": filename, "saved_at": datetime.now(timezone.utc).isoformat()},
                    indent=2,
                )
            )


def build_store() -> ResultStore:
    root = os.environ.get("OCRHUB_DATA_DIR", str(Path.home() / "data"))
    return ResultStore(root)
