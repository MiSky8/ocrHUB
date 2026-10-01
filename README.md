# ocrHub

One Docker image, several OCR engines, one API. Built after running
the same "which OCR engine works best for this document" comparison
by hand across two separate OCR pipeline projects — this bundles that
comparison into something you can run in one command.

![The ocrHub dashboard: the original page next to pdfplumber, Tesseract, Surya and Datalab](docs/images/dashboard-compare-engines.png)

## Included engines

| Engine | Version in this image | What it gives you | Runs |
|---|---|---|---|
| Tesseract | 5.5.0 (pytesseract 0.3.13) | text, per-word confidence, line boxes | local, always included |
| pdfplumber | 0.11.9 | the text layer of born-digital PDFs: fonts, colours, tables | local, always included |
| Surya | 0.14.7 (models: detection 2025-05-07, recognition 2025-05-16, layout and tables 2025-02-18) | line OCR, layout regions, reading order, tables | local, add with `ENGINES=surya` |
| Datalab | hosted API (`datalab-python-sdk` 0.5.0, mode `accurate`) | layout blocks, html tables, pictures | cloud, add with `ENGINES=datalab` and a `DATALAB_API_KEY` (paid, free monthly tier: [datalab.to](https://www.datalab.to)) |

These are the versions in the current image. Surya is pinned to 0.14.7; the
others follow what the image build installs. [docs/visualisations.md](docs/visualisations.md)
explains what each engine returns, how the dashboard draws it, and why newer
Surya releases aren't used yet.

## Quickstart

From this folder, with Docker running:

```bash
mkdir -p data              # your results are saved here
docker compose up --build
```

Open <http://localhost:8000>. Stop it with `Ctrl+C`.

That builds the smallest image: Tesseract and pdfplumber. To add Surya or
Datalab, copy the config template, edit it, and rebuild:

```bash
cp .env.example .env       # set ENGINES=surya,datalab and DATALAB_API_KEY
docker compose up --build
```

- **First build with Surya is slow:** several GB of packages, 15 to 60
  minutes. After that, code-only rebuilds take seconds. Only changing
  `ENGINES` or `pyproject.toml` reinstalls the packages.
- **Surya downloads its models on first use** (about 2 GB, kept in a Docker
  volume so it happens once), so its first run is slow too.
- `.env` is gitignored, so it's yours. Changing `ENGINES` needs a rebuild;
  other settings (such as `DATALAB_API_KEY`) only need `docker compose up`.

Without Compose:

```bash
docker build --build-arg ENGINES=surya,datalab -t ocrhub .
docker run -p 8000:8000 \
  -e DATALAB_API_KEY=your-key-here \
  -v ocrhub-models:/home/ocrhub/.cache \
  -v "$PWD/data:/home/ocrhub/data" ocrhub
```

(In PowerShell use `${PWD}`, in `cmd` use `%cd%`. The first volume keeps
Surya's models; without it they are downloaded again for every new container.)

To see what the app is doing (engine progress, errors, model downloads), run
`docker compose logs -f ocrhub` in a second terminal.

## Using it

**The dashboard** at <http://localhost:8000>: upload an image or PDF, tick the
engines to run, press **Run selected**. Each engine is its own request, so fast
engines show up while slow ones are still running. View the results **side by
side** or as an **overlay**, and switch boxes, text and reading-order numbers on
and off. Multi-page results get a page selector.

**The HTTP API:**

```bash
curl -s http://localhost:8000/engines        # which engines are available

curl -s -F "file=@document.pdf" -F "engines=tesseract" -F "engines=pdfplumber" \
  http://localhost:8000/ocr
```

`POST /ocr` takes a `file` and one or more `engines` fields, and an optional
`refresh=true` (see below).

### From an LLM

With ocrHub running (`docker compose up -d`), add it to an agent that speaks MCP,
for example Claude Code:

```bash
claude mcp add --transport http ocrhub http://localhost:8000/mcp/
```

Any MCP client that supports streamable HTTP can use the same URL. (Use the
trailing slash: `/mcp` redirects to `/mcp/`, and some clients don't follow
redirects on POST.) The server has one tool:

| Tool | Arguments | Returns |
|---|---|---|
| `ocr_document` | `file_base64`, `filename`, `engines` (a list), optional `refresh` | per engine: `text`, per-page text, `confidence`, `elapsed_ms`, `error` |

- Use engine names from `GET /engines`. An engine that isn't installed returns
  "engine not available" without stopping the others.
- The MCP tool returns **text only**: no boxes, no reading order, no page
  images. For those, use `POST /ocr` or the dashboard.
- The file travels as base64 inside the tool call, which suits small files.
  For large files, call `POST /ocr` with a file upload instead.

Any LLM tool that can run `curl` can use the HTTP API directly.

## Your results

Every `/ocr` request saves the uploaded file and each engine's result under a
directory named after the SHA-256 hash of the file's contents. With Compose this
is the plain folder `./data` next to `docker-compose.yml` (set `OCRHUB_DATA_DIR`
to put it elsewhere), so you can open the results straight from Finder or use
them from your own scripts:

```
data/input/<hash>-<original-filename>
data/output/<hash>/_meta.json          # original filename, timestamp
data/output/<hash>/<engine>.json       # that engine's result
```

Each `<engine>.json` holds the extracted text and, per page, the boxes
(coordinates, reading order, region type, and engine extras such as html tables,
fonts and word confidences). [docs/visualisations.md](docs/visualisations.md)
describes what each engine puts in it.

**It's also the cache.** If a file's hash already has a saved result for an
engine, `/ocr` returns it instead of running that engine again. That saves
the wait and, for Datalab, the cost. Pass `refresh=true` as a form field on `/ocr`
(or the MCP tool's `refresh` argument) to force a fresh run. A failed result is
never cached. After changing an engine's code, delete its old `<engine>.json`
or use `refresh=true`, or the dashboard keeps showing the old output.

## Speed, memory and limits

The engines run on CPU inside the container. These timings are from our own
tests on a Docker Desktop Mac (8 GB limit), so treat them as rough:

| Engine | Typical time | Memory |
| --- | --- | --- |
| pdfplumber | under a second (born-digital PDFs only) | tiny |
| Tesseract | 2-20 s per page (longer for dense pages) | small |
| Datalab | 10 s - 2.5 min in our tests (hosted, so it depends on their queue) | none locally |
| Surya | ~3 min for a 2-page PDF or a receipt photo with layout and tables on (**12 min** for a dense newspaper page, measured with lines only) | **about 6 GB** |

- **Surya's layout and table models** run after text recognition and give it
  regions, reading order and tables. They cost some time and memory. Set
  `SURYA_LAYOUT=0` in `.env` to skip them and get plain lines.
- **Images** are normalised before any engine sees them: EXIF rotation applied,
  flattened to RGB, longest side capped at 3000 px, re-encoded as PNG. The
  original is kept untouched in `data/input`.
- **HEIC** files (iPhone photos exported directly, for example via AirDrop) are
  not supported yet. Export them as JPEG first.
- **Dense pages** such as newspapers are best uploaded as born-digital PDFs.
  Photographed pages are slower and less accurate.
- **CPU only.** The image has no CUDA build of PyTorch, so a GPU on the host isn't
  used, and on macOS no container can reach the GPU at all (Docker Desktop runs
  containers in a Linux VM). On Linux with an NVIDIA GPU you'd have to build a
  CUDA variant of this image and run with `--gpus all`; this image doesn't do
  that.

## Troubleshooting

**The page looks wrong after an update.** Rebuild with
`docker compose up --build` and hard-refresh the browser (Cmd+Shift+R).

**The build fails with `No space left on device`.** Docker's disk is full. Check
with `docker system df`, then free it:

```bash
docker builder prune -a -f && docker image prune -f
```

This doesn't touch your saved results or downloaded models, but it deletes the
build cache, so the next build reinstalls everything (slow). A plain
`docker builder prune -f` keeps recent cache and may free nothing. To stop it
recurring, raise Docker Desktop > Settings > Resources > Disk image size.

**Surya, or the whole container, just disappears with no error.** It was almost
certainly killed for running out of memory: Docker Desktop's default limit is
about 8 GB and Surya alone can use 5-6 GB. Confirm with:

```bash
docker inspect ocrhub-ocrhub-1 --format 'OOMKilled={{.State.OOMKilled}} exit={{.State.ExitCode}}'
```

`OOMKilled=true` or exit code 137 means yes. Restart with `docker compose up -d`
and either give Docker more memory (Docker Desktop > Settings > Resources) or
lower Surya's batch sizes in `.env`. Smaller is slower but uses less memory, and
these defaults are already conservative:

```
SURYA_RECOGNITION_BATCH_SIZE=8
SURYA_DETECTOR_BATCH_SIZE=1
```

**A long Surya run shows "Failed to fetch".** Surya on a dense page (a newspaper,
say) takes 15 to 40 minutes. Keep the computer awake while it runs (on a Mac, run
`caffeinate -i` in a terminal): if it goes to sleep, the browser's connection
drops. The run itself carries on and the result is saved, so once
`docker compose logs ocrhub` shows the layout step finished, choose the same file
and Surya again and the saved result appears straight away.

### Folder permissions

The container runs as a normal user, `ocrhub` (user ID 1000), not as root, so it
can only save results if that user may write to `./data`.

- **macOS (Docker Desktop):** works with no setup. This is where it was tested.
- **Linux:** create the folder yourself before the first start (`mkdir -p data`).
  If you don't, Docker creates it owned by root and the app can't write to it. If
  your account isn't user 1000, give the folder to the container's user:
  `sudo chown -R 1000:1000 data`. On SELinux systems (Fedora, RHEL) also add `:z`
  to the volume in `docker-compose.yml` (`./data:/home/ocrhub/data:z`). We
  haven't tested Linux ourselves.
- **Windows (Docker Desktop, WSL 2):** Windows folders don't enforce Linux user
  IDs, so this normally works. Keeping the project inside the WSL filesystem (for
  example under `~/`) is much faster than under `C:\`. We haven't tested Windows
  ourselves.

If the folder can't be written, ocrHub still returns every OCR result. It just
doesn't save or cache them, and says so in the log (`docker compose logs ocrhub`),
including a warning at startup.

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

Engines are mocked, so no Docker or downloads are needed. See
[CONTRIBUTING.md](CONTRIBUTING.md) if you want to help.

## License

MIT — see `LICENSE`.
