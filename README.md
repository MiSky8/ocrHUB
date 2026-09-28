# ocrHub

One Docker image, several OCR engines, one API. Built after running
the same "which OCR engine works best for this document" comparison
by hand across two separate OCR pipeline projects — this bundles that
comparison into something you can run in one command.

## Quickstart

```bash
docker build --build-arg ENGINES=surya,paddleocr -t ocrhub .
docker run -p 8000:8000 -e OLLAMA_HOST=http://host.docker.internal:11434 ocrhub
```

Open `http://localhost:8000` to upload a document and compare engines
side by side, or call the REST API directly:

```bash
curl -s http://localhost:8000/engines

curl -s -F "file=@document.pdf" -F "engines=tesseract" -F "engines=pdfplumber" \
  http://localhost:8000/ocr
```

An MCP server is also mounted at `/mcp`, exposing an `ocr_document`
tool for agent frameworks that speak MCP. Note: the endpoint redirects
to a trailing slash (`POST /mcp` 307s to `POST /mcp/`), which is
standard behavior for a mounted sub-app. Any redirect-following HTTP
client handles this transparently, but MCP clients that don't follow
redirects on POST should target `/mcp/` directly.

## Engines

| Engine | Type | Install | Notes |
|---|---|---|---|
| Tesseract | local, CPU | default-on | classic baseline OCR |
| pdfplumber | local, CPU | default-on | text extraction for born-digital PDFs, not OCR |
| Surya | local, GPU-friendly | `ENGINES=surya` | modern layout-aware OCR |
| PaddleOCR | local, GPU-friendly | `ENGINES=paddleocr` | strong multilingual support |
| DeepSeek (via Ollama) | self-hosted vision model | set `OLLAMA_HOST` | point at your own Ollama instance |

## Build args

`ENGINES` is a comma-separated list of optional extras to install at
build time (currently: `surya`, `paddleocr`). Tesseract and pdfplumber
are always installed. Leave `ENGINES` unset for the smallest image.

## Why

<!-- TODO: add your name/business and site link -->
Built and maintained by [your name/business] — automation and
document-processing pipelines. If you need this kind of thing built
into your own pipeline, [link to your site/contact].

## License

MIT — see `LICENSE`.
