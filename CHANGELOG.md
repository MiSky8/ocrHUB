# Changelog

## 0.1.0 (2026-10-01)

First release. Version 0.1.0 matches `pyproject.toml`.

### Included
- Four engines behind one API: Tesseract 5.5.0, pdfplumber 0.11.9, Surya 0.14.7
  and Datalab (hosted API, `datalab-python-sdk` 0.5.0).
- A comparison dashboard: engines side by side or as an overlay, boxes, text
  and reading-order numbers, a detections table, and a page selector for
  multi-page documents.
- Surya with its layout and table models: regions, reading order and html
  tables (`SURYA_LAYOUT=0` returns plain lines instead).
- pdfplumber with the PDF's real fonts, colours, tables and pictures, and column
  splitting.
- `POST /ocr` and `GET /engines` over HTTP, and an `ocr_document` tool over MCP
  at `/mcp/`.
- Results saved to `./data` and reused as a cache, keyed by file content
  (`refresh=true` forces a new run). If the folder can't be written, results are
  still returned.
- A slim image (Tesseract and pdfplumber) on GitHub's container registry,
  `ghcr.io/misky8/ocrhub`, for linux/amd64 and linux/arm64. The arm64 image was run
  natively on Apple Silicon and the amd64 image under emulation on the same
  machine; neither has been run on a Linux host.
- Documentation: a README, a visualisation guide (`docs/visualisations.md`) and
  `CONTRIBUTING.md`.

### Known limitations
- Tested on macOS (Docker Desktop, Apple Silicon). Linux and Windows are
  untested.
- CPU only. Surya takes minutes per page (15 to 40 minutes for a dense page)
  and needs about 6 GB of memory.
- Surya is pinned to 0.14.7. Newer releases change the recogniser and are not
  supported yet.
- HEIC images are not supported.
- The MCP tool returns text only, without boxes or page images.
