# ocrHub

One Docker image, several OCR engines, one API. Built after running
the same "which OCR engine works best for this document" comparison
by hand across two separate OCR pipeline projects — this bundles that
comparison into something you can run in one command.

## Quickstart

**Fastest way** - from this folder, with Docker running:

```bash
mkdir -p data              # results are saved here; see "Folder permissions" if it fails
docker compose up --build
```

Then open <http://localhost:8000>. Stop it with `Ctrl+C`. (This builds the
smallest image: tesseract + pdfplumber only. To add more engines, see below.)

The first build is slow: with Surya it downloads several GB of packages and
can take 15-60 minutes. After that, rebuilds that only change the code take
seconds. Only changing `ENGINES` or `pyproject.toml` reinstalls the packages.
Surya also downloads its model on first use, so its first run is slow too.

To see what the app is doing (engine progress, errors, model downloads),
open a second terminal in this folder and run:

```bash
docker compose logs -f
```

If the page looks wrong after an update, rebuild with
`docker compose up --build` and hard-refresh the browser (Cmd+Shift+R).

If a build fails with `No space left on device`, Docker's disk is full.
Check with `docker system df`, then free it:

```bash
docker builder prune -a -f && docker image prune -f
```

This doesn't touch your saved results or downloaded models, but it deletes
the build cache, so the next build reinstalls everything (slow, see above).
A plain `docker builder prune -f` keeps recent cache and may free nothing.
To stop it recurring, raise Docker Desktop -> Settings -> Resources -> Disk
image size.

**One config file, one command:** copy `.env.example` to
`.env`, edit it to pick which engines to build (`ENGINES=`) and set any
runtime config (`DATALAB_API_KEY`, ...), then:

```bash
cp .env.example .env   # edit .env to taste
docker compose up --build
```

`.env` is gitignored - it's yours to edit locally, `.env.example` is the
tracked template. Re-run `docker compose up --build` any time you change
`ENGINES` in `.env`; a plain `docker compose up` picks up changes to the
other (runtime-only) variables without rebuilding.

**Plain `docker build`/`docker run`** works too, if you'd rather not use
Compose - `ENGINES` is a build arg, everything else is a runtime `-e`:

```bash
docker build --build-arg ENGINES=surya,datalab -t ocrhub .
docker run -p 8000:8000 \
  -e DATALAB_API_KEY=your-key-here \
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

## Use from an LLM

With ocrHub running (`docker compose up -d`), a language model can call it
in two ways.

**MCP (agents such as Claude Code).** Add the server once:

```bash
claude mcp add --transport http ocrhub http://localhost:8000/mcp/
```

Any other MCP client that supports streamable HTTP can use the same URL,
`http://localhost:8000/mcp/`. The server has one tool:

| Tool | Arguments | Returns |
|---|---|---|
| `ocr_document` | `file_base64`, `filename`, `engines` (a list), optional `refresh` | per engine: `text`, per-page text, `confidence`, `elapsed_ms`, `error` |

- Use engine names from `GET /engines` (for example `tesseract`, `pdfplumber`,
  `surya`, `datalab`). An engine that isn't installed returns
  "engine not available" without stopping the others.
- The MCP tool returns **text only**: no boxes, no reading order, no page
  images. For those, use the HTTP API (`POST /ocr`) or the dashboard.
- The file travels as base64 inside the tool call, which suits small files.
  For large files or whole folders, let your script call `POST /ocr` with a
  file upload instead (see Batch processing).

**HTTP API (any LLM tool that can run `curl` or make requests).**
`GET /engines` lists what is available and `POST /ocr` takes a `file` and one
or more `engines` form fields. Results are cached by file content, so asking
again for the same file and engine is instant.

## Engines

| Engine | Type | Install | Notes |
|---|---|---|---|
| Tesseract | local, CPU | default-on | classic baseline OCR |
| pdfplumber | local, CPU | default-on | text extraction for born-digital PDFs, not OCR |
| Surya | local, CPU (in-container) | `ENGINES=surya` | modern layout-aware OCR: regions, reading order, tables |
| Datalab | hosted API | `ENGINES=datalab` + set `DATALAB_API_KEY` | paid, has a free monthly tier - see [datalab.to](https://www.datalab.to) |

See [docs/visualisations.md](docs/visualisations.md) for how the dashboard
draws each engine's output and what each one does and doesn't return.

## Build args

`ENGINES` is a comma-separated list of optional extras to install at
build time (currently: `surya`, `datalab`). Tesseract and
pdfplumber are always installed. Leave `ENGINES` unset for the smallest
image.

## Persistent model cache

Surya downloads its model weights on first use (not baked into the
image, to keep the base build small): the recognition model alone is
~1.6GB, plus the detection, layout and table models. They cache under
`/home/ocrhub/.cache` inside the container. Without a mounted volume, that cache is lost
every time the container is removed or recreated, so you'll re-pay
that download on every fresh `docker run`.

Mount a named volume to persist it across runs, as shown in the
Quickstart above (`-v ocrhub-models:/home/ocrhub/.cache`) — the second and
subsequent runs then start Surya instantly instead of
re-downloading its weights.

## Persistent input/output storage

Every `/ocr` request saves the uploaded file and each engine's result
under a directory named after the SHA-256 hash of the file's contents.
With `docker compose` this is the plain folder **`./data`** next to
`docker-compose.yml` (set `OCRHUB_DATA_DIR` to put it elsewhere), so you can
open the results straight from Finder or use them from your own scripts:

```
data/input/<hash>-<original-filename>
data/output/<hash>/_meta.json          # original filename, timestamp
data/output/<hash>/<engine>.json       # that engine's OcrResult
```

Each `<engine>.json` holds the extracted text, and per page the boxes
(coordinates, reading order, region type). Extras by engine:

- **Datalab:** boxes keep the original `html` (lists, tables), and the file has
  a `raw` field with Datalab's untouched response.
- **pdfplumber:** one box per text line with the PDF's real font in `style`
  (font, size, bold, italic, colour, and per-run styles); detected tables are
  `Table` boxes with `html`.
- **Pictures (Datalab, pdfplumber):** `region_type: "Picture"` boxes with the
  cropped image as base64 JPEG in `image`; Datalab also gives its alt
  text/caption in `text`. Surya's picture regions are cropped too; Tesseract doesn't detect pictures.
- **Tesseract:** one box per line, with the individual words (and their
  confidences) nested in `words`; page confidence is the mean word confidence.

With plain `docker run`, add `-v "$PWD/data:/home/ocrhub/data"` (in
PowerShell use `${PWD}`, in `cmd` use `%cd%`).

### Folder permissions

The container runs as a normal user, `ocrhub` (user ID 1000), not as root, so
it can only save results if that user may write to `./data`.

- **macOS (Docker Desktop):** works with no setup. This is where it was
  tested.
- **Linux:** create the folder yourself before the first start (`mkdir -p
  data`). If you don't, Docker creates it owned by root and the app can't
  write to it. If your account isn't user 1000, give the folder to the
  container's user: `sudo chown -R 1000:1000 data`. On SELinux systems
  (Fedora, RHEL) also add `:z` to the volume in `docker-compose.yml`
  (`./data:/home/ocrhub/data:z`). We haven't tested Linux ourselves.
- **Windows (Docker Desktop, WSL 2):** Windows folders don't enforce Linux
  user IDs, so this normally works. Keeping the project inside the WSL
  filesystem (for example under `~/`) is much faster than under `C:\`. We
  haven't tested Windows ourselves.

If the folder can't be written, ocrHub still returns every OCR result. It
just doesn't save or cache them, and says so in the log (`docker compose logs
ocrhub`), including a warning at startup.

This is also the result cache: if the same file's hash already has a
saved result for a given engine, `/ocr` returns it instead of re-running
that engine - useful for anything slow (Surya, a paid Datalab
call) where you don't want to re-pay the cost on a file you already
processed. Pass `refresh=true` as a form field on `/ocr` (or the MCP
tool's `refresh` argument) to force recomputation. A failed result is
never cached, so a transient error doesn't permanently poison it.

## Batch processing

There's no separate batch API - `/ocr` (and the MCP `ocr_document` tool)
already take one file per call, and that's enough to process a whole
folder: loop over it yourself. Every result still lands in the persistent
store above, so re-running the same loop after a partial failure only
recomputes what's missing.

```bash
for f in ~/my-dataset/*; do
  curl -s -F "file=@$f" -F "engines=tesseract" -F "engines=surya" \
    http://localhost:8000/ocr | jq -c '.results[] | {engine, ok, elapsed_ms}'
done
```

An agent with shell access can run the same loop for you. See
[Use from an LLM](#use-from-an-llm).

## Memory, speed and input limits

The engines run on CPU inside the container. Timings below are from our own
tests on a Docker Desktop Mac (8 GB limit), so treat them as rough:

| Engine | Typical time | Memory |
| --- | --- | --- |
| pdfplumber | under a second (born-digital PDFs only) | tiny |
| Tesseract | 2-20 s per page (longer for dense pages) | small |
| Datalab | 10 s - 2.5 min in our tests (hosted, so it depends on their queue) | none locally |
| Surya | ~3 min for a 2-page PDF or a receipt photo with layout and tables on (**12 min** for a dense newspaper page, measured with lines only) | **about 6 GB** |

**If Surya (or the whole container) just disappears with no error**, it was
almost certainly killed for running out of memory: Docker Desktop's default
limit is about 8 GB and Surya alone can use 5-6 GB. Confirm with:

```bash
docker inspect ocrhub-ocrhub-1 --format 'OOMKilled={{.State.OOMKilled}} exit={{.State.ExitCode}}'
```

`OOMKilled=true` / exit code 137 means yes. Restart with `docker compose up -d`
and either give Docker more memory (Docker Desktop > Settings > Resources) or
lower Surya's batch sizes in `.env` (smaller is slower but uses less memory;
the defaults are already conservative):

```
SURYA_RECOGNITION_BATCH_SIZE=8
SURYA_DETECTOR_BATCH_SIZE=1
```

Surya also runs its layout and table models after recognition. They give it
regions, a reading order and tables, and download on first use. They cost
some time and memory; set `SURYA_LAYOUT=0` in `.env` to skip them.

Watch what the container is doing with `docker compose logs -f ocrhub`.

**Long runs.** Surya on a dense page (a newspaper, say) takes 15 to 40
minutes. Keep the computer awake while it runs (on a Mac, run `caffeinate -i`
in a terminal): if it goes to sleep, the browser's connection drops and the page
shows "Failed to fetch". The run itself carries on and the result is saved, so
once `docker compose logs ocrhub` shows the layout step finished, choose the
same file and Surya again and the saved result appears straight away.

Every engine you tick is sent as its own request, so fast engines show their
results while slow ones are still running, and results are cached on disk
either way: if you close the tab during a long Surya run, re-uploading the
same file later returns whatever finished.

**Images.** Uploads are normalised before any engine sees them: the EXIF
rotation is applied (phone photos are stored sideways), the image is
flattened to RGB, its longest side is capped at 3000 px and it is re-encoded
as PNG. The original is kept untouched in `data/input`. HEIC files (iPhone
photos exported directly, e.g. via AirDrop) are not supported yet - export
them as JPEG first. Dense pages such as newspapers are best uploaded as
born-digital PDFs; photographed pages will be slower and less accurate.

## GPU acceleration

Everything running **inside** this container (Tesseract, pdfplumber, Surya)
is CPU-only. That's true regardless of your host hardware, including on
machines with an NVIDIA GPU: the image doesn't include CUDA-enabled builds
of PyTorch, so a GPU present on the host isn't used by the containerised
engines.

On **macOS specifically**, no container can access the host GPU at all
(Apple Silicon or Intel): Docker Desktop on Mac runs containers inside a
Linux VM with no Metal passthrough. This is a Docker-on-Mac platform
limitation, not something this image can work around.

If you're on Linux with an NVIDIA GPU and want Surya accelerated, you'd need
to build a variant of this image against CUDA-enabled PyTorch wheels and
pass `--gpus all` at `docker run`. This image doesn't do that out of the box
(it is intentionally CPU-only and portable).

## Running the tests

```bash
pip install -e ".[dev]"
pytest -q
```

Engines are mocked, so no Docker or downloads are needed.

See [CONTRIBUTING.md](CONTRIBUTING.md) if you want to help.

## Why

<!-- TODO: add your name/business and site link -->
Built and maintained by [your name/business] — automation and
document-processing pipelines. If you need this kind of thing built
into your own pipeline, [link to your site/contact].

## License

MIT — see `LICENSE`.
