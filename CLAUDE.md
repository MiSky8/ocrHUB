# ocrHub

One Docker image, several OCR engines (pdfplumber, Tesseract, Surya, Datalab),
one HTTP API, one MCP tool and one comparison dashboard. See `README.md` for
usage and `docs/visualisations.md` for what each engine returns and how the
dashboard draws it.

## Commands

```bash
pip install -e ".[dev]" && pytest -q     # tests; no OCR models needed (Surya and Datalab are mocked)
docker compose up -d --build              # rebuild and restart after code changes
docker compose logs -f ocrhub             # engine progress, errors, model downloads
```

A code-only rebuild takes seconds. Changing `pyproject.toml` or `ENGINES`
reinstalls the packages (slow, Surya is several GB). CI runs `pytest` on
Python 3.11 with Tesseract installed.

## Layout

- `src/ocrhub/adapters/<engine>_adapter.py`: one adapter per engine, each with
  `name`, `available()` and `extract(file_bytes, filename) -> OcrResult` (see
  `adapters/base.py`). Results use the dataclasses in `models.py`.
- `service.py`: runs the requested engines, normalises images, reads and writes
  the result cache. `api.py` (FastAPI, `/ocr`, `/engines`, `/health`),
  `mcp_server.py` (`ocr_document` at `/mcp/`), `main.py` (wires both).
- `web/static/app.js`, `web/templates/index.html`: the dashboard (no build step).
- `storage.py`: results go to `data/output/<sha256>/<engine>.json`. `data/` is
  gitignored and holds user files, so never commit or delete it.

## Things that are easy to get wrong

- **Results are cached by file content.** After changing an adapter, old
  `data/output/<hash>/<engine>.json` files still show old behaviour. Delete
  the file or send `refresh=true` to `/ocr`.
- **Surya is pinned to `surya-ocr==0.14.7`** (and `numpy<2`). Newer lines change
  the recogniser's construction and, from 0.20, drop per-line confidence. See
  the Versions section of `docs/visualisations.md` before bumping it.
- **Surya memory:** it peaks near 6 GB on CPU. Its models (detection and
  recognition, then layout, then tables) run one at a time and are released
  between stages. Keep it that way. `SURYA_LAYOUT=0` turns the layout and
  table stage off.
- **Engines report different coordinates:** PDF points for pdfplumber, pixels
  for the others. The dashboard sizes things from each page's own space, so
  don't assume a fixed page width.
- **The MCP tool deliberately returns text only** (no boxes or page images).
- Engines that fail return an `OcrResult` with `error` set and are never
  cached. Keep that per-engine isolation: one engine failing must not stop
  the others.
- Tests mock the heavy engines. A passing test run says nothing about real model
  output, so run a real file through the container when changing an adapter.
