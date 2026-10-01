# Contributing to ocrHub

Thanks for helping. This page covers how to run the project, what to check
before opening a pull request, and where things live. `README.md` explains how
to use ocrHub, and `CLAUDE.md` has a longer list of things that are easy to get
wrong (it is written for coding agents but reads fine for people).

## Set up and run the tests

```bash
git clone https://github.com/MiSky8/ocrHUB.git && cd ocrHUB
pip install -e ".[dev]"
pytest -q
```

You need Python 3.11 or newer and the `tesseract` program (for example
`brew install tesseract` or `sudo apt-get install tesseract-ocr`). Surya and
Datalab are mocked in the tests, so no models or API keys are needed. CI runs the
same `pytest` on every push and pull request.

## Run the app

```bash
docker compose up -d --build     # then open http://localhost:8000
docker compose logs -f ocrhub
```

A code-only rebuild takes seconds. Changing `pyproject.toml` or `ENGINES` in
`.env` reinstalls the packages, which is slow when Surya is included. See the
README for engine options and memory notes.

## Before you open a pull request

- Run `pytest -q` and make sure it passes.
- If you changed an adapter or the dashboard, **run a real file through the
  container** and look at the result. The tests mock the heavy engines, so a green
  run says nothing about real OCR output.
- Saved results are cached by file content in `data/output/`. After changing an
  adapter, delete the old `<engine>.json` or send `refresh=true`, or you will keep
  seeing the old output.
- Add or update tests for behaviour you change. Adapter tests are in
  `tests/adapters/`.
- Keep a failing engine from stopping the others. Engines return an
  `OcrResult` with `error` set instead of raising.
- Update `README.md` or `docs/visualisations.md` when behaviour users can see
  changes.
- Keep the pull request to one change. A short description of what and why is
  enough.

## Adding or changing an engine

An engine is one class in `src/ocrhub/adapters/` with a `name`, an
`available()` method and an `extract(file_bytes, filename)` method that returns an
`OcrResult` (see `adapters/base.py` and `models.py`). Register it in
`build_registry()` in `src/ocrhub/api.py`, and add a colour for it in
`ENGINE_COLORS` in `src/ocrhub/web/static/app.js`. If it needs extra packages, add
an extra in `pyproject.toml` and pin the version you tested, with a comment
saying why.

Please do not bump the pinned Surya version (`surya-ocr==0.14.7`) without reading
the Versions section of `docs/visualisations.md`. Newer lines change how the
recogniser is built.

## Reporting bugs

Open an issue with the engine, the file type, what you expected and what you got.
The container log (`docker compose logs ocrhub`) helps, especially for Surya
running out of memory. Please do not attach documents that contain private data.

## License

By contributing you agree that your work is released under the MIT license in
`LICENSE`.
