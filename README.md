
# PaddleOCR Studio

A local web app for running [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) over PDFs and
images and inspecting the results — extracted text, per-line confidence scores, and bounding boxes
overlaid on the page.

Everything runs on your machine. Nothing is uploaded anywhere.

---

## Quick start

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux / macOS

# 2. Install dependencies (first run downloads ~200 MB of models)
pip install -r requirements.txt

# 3. Start the server
python server.py
```

Then open <http://localhost:8060>.

```bash
python server.py 9000          # use a different port
```

The first OCR run loads the PP-OCRv6 models and takes noticeably longer than later ones. The
models are cached after that.

---

## Using it

1. Click **Run New OCR**.
2. Drag in a PDF or image (or type an absolute path to a file already on disk).
3. For PDFs, pick *first page*, a *page range*, or *all pages*.
4. Click **Execute OCR**.

The job runs in the background. You can close the dialog and keep browsing earlier results —
each page appears in the document list the moment it is written to disk.

### Reading the results

| Pane | What it gives you |
| --- | --- |
| **Left viewport** | The annotated page. Hover a box to highlight its row; click one to jump to it. Toggle **Original** for the unannotated source page. |
| **Plain Text** | The full extraction as numbered lines, raw text, or one paragraph. |
| **JSON Output** | A clean structured payload, or PaddleOCR's raw output verbatim. |
| **Line Inspector** | Every line with its confidence score and box bounds. |

The **Page / All** toggle switches between one page and every page of the document combined.
**Copy** and **Download** always export exactly what is on screen, filters included.

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| <kbd>←</kbd> / <kbd>→</kbd> | Previous / next page |
| <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> | Switch tab |
| <kbd>+</kbd> / <kbd>−</kbd> / <kbd>0</kbd> | Zoom in / out / fit |
| <kbd>Ctrl</kbd>+<kbd>N</kbd> | New OCR run |
| <kbd>Esc</kbd> | Close the dialog |

Hold <kbd>Ctrl</kbd> and scroll to zoom the page; drag to pan when zoomed in.

---

## File access and security

The server binds to `127.0.0.1` only, and **reads files solely from inside the project folder**.
That restriction matters: without it, any website open in your browser could ask the server for
arbitrary files on your disk and read the response.

To OCR files that live elsewhere, opt that folder in explicitly:

```bash
# Windows
set OCR_ALLOWED_DIRS=D:\scans;E:\invoices
python server.py

# Linux / macOS
OCR_ALLOWED_DIRS=/data/scans:/data/invoices python server.py
```

Paths outside the allowed roots are refused with a `403`, and the **Original** view is disabled
for documents whose source file is no longer readable.

Two more guards worth knowing about:

- Uploads are capped at **256 MB** and limited to the extensions in `ALLOWED_UPLOAD_SUFFIXES`.
  Filenames are flattened to a single path segment, and an upload never overwrites an existing
  file — it gets a timestamp suffix instead.
- Requests whose `Host` header is not a loopback name are rejected, which blocks DNS-rebinding
  attempts against the local server.

**Do not expose this to a network.** `--host 0.0.0.0` exists for container use, but there is no
authentication of any kind — anyone who can reach the port can read your documents and run jobs.

---

## Project Layout

```
OCR_CLASSIFIER/
├── pyproject.toml         Packaging, metadata, and pytest configuration
├── requirements.txt       Pinned Python dependencies
├── README.md              This guide
├── server.py              HTTP server, OCR job runner, results API
├── ocr.py                 Minimal standalone CLI OCR runner
├── pipeline.py            End-to-end extraction CLI (router -> reader -> A -> B)
│
├── schema.py              Two-layer document schema & cell provenance
├── column_mapper.py       Stage A: Column role mapping & sectioning
├── validator.py           Stage B: Accounting & balance validation gate
│
├── readers/               Per-format readers (Excel, PDF Text, OCR, Router, Geometry)
├── web/                   Frontend UI (index.html, styles.css, app.js)
├── docs/                  Documentation hub (PIPELINE.md, BENCHMARK.md, TEST_REPORT.md)
├── benchmarks/            Benchmark harness, profiling utilities, and cached results
├── tests/                 126 automated unit and integration tests
├── output/                PaddleOCR artifacts: <run_id>_res.json + _ocr_res_img.<ext>
└── uploads/               Files uploaded through the web UI
```

### Documentation & Architecture Links

- **[Pipeline Architecture (docs/PIPELINE.md)](docs/PIPELINE.md)**: Two-layer extraction pipeline, Stage A column mapping, and Stage B validation gate.
- **[Benchmark Analysis (docs/BENCHMARK.md)](docs/BENCHMARK.md)**: 31-document distributor corpus benchmark, timing, and error analysis.
- **[Test Report (docs/TEST_REPORT.md)](docs/TEST_REPORT.md)**: Comprehensive test suite results and coverage analysis.
- **[Benchmarking Guide (benchmarks/README.md)](benchmarks/README.md)**: How to run evaluation benchmarks and performance profiling.

### How results are grouped

PaddleOCR writes one `<run_id>_res.json` and one annotated image per page. The server reads the
`input_path` and `page_index` from each JSON header and groups pages into documents:

- **Images** → one document, one page. `run_id` is the filename stem.
- **PDFs** → one document per source file, with `run_id = <stem>_<zero-based page index>`.

`output/` is the single source of truth. Delete a JSON and its page disappears from the UI;
there is no separate database.

---

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Server status, whether the engine is loaded, allowed roots |
| `GET` | `/api/documents` | All documents with their ordered pages |
| `GET` | `/api/output/<run_id>` | Full detail for one page |
| `GET` | `/api/document-combined/<doc_id>` | Every page of a document in one payload |
| `GET` | `/api/job/<job_id>` | Progress of a running OCR job |
| `GET` | `/api/raw-image?path=…` | Serve a source image (allowed roots only) |
| `GET` | `/api/pdf-page-image?path=…&page=N` | Render one PDF page as JPEG |
| `POST` | `/api/upload` | Upload a file to `uploads/` |
| `POST` | `/api/run-ocr` | Start a job — returns `202` with a `job_id` |

`/api/run-ocr` returns immediately; poll `/api/job/<job_id>` for `status`, `pages_done`,
`pages_expected`, and the `run_id` of each finished page.

---

## Notes and limits

- **Inference is serialised.** Paddle predictors are not safe to share across threads, so
  concurrent OCR requests queue behind one lock. The HTTP server stays responsive throughout.
- **Page ranges still decode earlier pages.** PaddleOCR's `predict()` yields pages in order, so
  asking for pages 5–8 of a PDF runs detection on 1–4 first and discards them. *First page only*
  does stop early and is genuinely fast.
- **Model choice is hard-coded** in `get_ocr_engine()` (`PP-OCRv6_medium` det + rec, MKLDNN off,
  no orientation/unwarping). Edit it there if you need a different configuration.
- **Job history is in memory.** Restarting the server clears it; the OCR results in `output/`
  survive.

---

## Troubleshooting

**"That path is outside the allowed folders"** — set `OCR_ALLOWED_DIRS` as shown above, or upload
the file through the UI instead.

**The "Original" toggle is greyed out** — the document's source file was moved, deleted, or sits
outside the allowed roots. The annotated view still works.

**First run hangs for a minute** — it is downloading the PP-OCRv6 models. Subsequent runs are
fast.

**`ModuleNotFoundError: paddle`** — the virtual environment is not active, or
`pip install -r requirements.txt` has not been run in it.
