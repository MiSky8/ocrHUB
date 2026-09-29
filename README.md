# ocrHub

One Docker image, several OCR engines, one API. Built after running
the same "which OCR engine works best for this document" comparison
by hand across two separate OCR pipeline projects — this bundles that
comparison into something you can run in one command.

## Quickstart

```bash
docker build --build-arg ENGINES=surya,paddleocr -t ocrhub .
docker run -p 8000:8000 -e OLLAMA_HOST=http://host.docker.internal:11434 \
  -v ocrhub-models:/home/ocrhub/.cache ocrhub
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
| Surya | local, CPU (in-container) | `ENGINES=surya` | modern layout-aware OCR |
| PaddleOCR | local, CPU (in-container) | `ENGINES=paddleocr` | strong multilingual support |
| DeepSeek (via Ollama) | self-hosted vision model | set `OLLAMA_HOST` | point at your own Ollama instance, runs natively outside this container |

## Build args

`ENGINES` is a comma-separated list of optional extras to install at
build time (currently: `surya`, `paddleocr`). Tesseract and pdfplumber
are always installed. Leave `ENGINES` unset for the smallest image.

## Persistent model cache

Surya and PaddleOCR download their model weights on first use (not
baked into the image, to keep the base build small) — Surya's
recognition model alone is ~1.6GB. Both cache under `/home/ocrhub/.cache`
inside the container. Without a mounted volume, that cache is lost
every time the container is removed or recreated, so you'll re-pay
that download on every fresh `docker run`.

Mount a named volume to persist it across runs, as shown in the
Quickstart above (`-v ocrhub-models:/home/ocrhub/.cache`) — the second and
subsequent runs then start these engines instantly instead of
re-downloading their weights.

## GPU acceleration

Everything running **inside** this container — Tesseract, pdfplumber,
Surya, PaddleOCR — is CPU-only. That's true regardless of your host
hardware, including on machines with an NVIDIA GPU: the published
image doesn't include CUDA-enabled builds of PyTorch/PaddlePaddle, so
a GPU present on the host isn't used by the containerized engines.

On **macOS specifically**, no container can access the host GPU at
all (Apple Silicon or Intel) — Docker Desktop on Mac runs containers
inside a Linux VM with no Metal passthrough. This is a Docker-on-Mac
platform limitation, not something this image can work around.

The one engine that *does* get GPU acceleration on your machine is
**Ollama/DeepSeek** — because it isn't bundled in this container at
all. You run Ollama natively on your host (where it can use Metal on
Mac or CUDA on Linux/Windows), and ocrHub just calls it over HTTP via
`OLLAMA_HOST`. If you want GPU speed today, that's the path.

If you're on Linux with an NVIDIA GPU and want Surya/PaddleOCR
accelerated too, you'd need to build a variant of this image against
CUDA-enabled PyTorch/PaddlePaddle wheels and pass `--gpus all` at
`docker run` — not something this image does out of the box (v1 is
intentionally CPU-only/portable), but a reasonable fast-follow if
there's interest.

Separately: `paddleocr` is pinned to `2.7.3` (not the current `3.x`)
because `3.x` broke its API and, in testing on Apple Silicon (arm64),
segfaulted at inference time. `2.7.3` is the last version verified
stable in this image.

## Why

<!-- TODO: add your name/business and site link -->
Built and maintained by [your name/business] — automation and
document-processing pipelines. If you need this kind of thing built
into your own pipeline, [link to your site/contact].

## License

MIT — see `LICENSE`.
