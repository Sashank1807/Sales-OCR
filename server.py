#!/usr/bin/env python3
"""PaddleOCR Studio - a local OCR extraction server and result inspector.

Serves the web UI in web/, runs PaddleOCR jobs in the background, and exposes
the results in output/ as a grouped document API.
"""

import argparse
import io
import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn

# Must be set before any Paddle import happens.
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
WEB_DIR = BASE_DIR / "web"
UPLOADS_DIR = BASE_DIR / "uploads"
for _d in (OUTPUT_DIR, WEB_DIR, UPLOADS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Files may only be read from inside these roots. Everything the app writes
# lives under BASE_DIR; additional source folders can be opted in with
# OCR_ALLOWED_DIRS (os.pathsep separated), e.g. OCR_ALLOWED_DIRS=D:\scans
ALLOWED_ROOTS = [BASE_DIR]
for _extra in os.environ.get("OCR_ALLOWED_DIRS", "").split(os.pathsep):
    _extra = _extra.strip()
    if _extra:
        try:
            ALLOWED_ROOTS.append(Path(_extra).resolve())
        except (OSError, ValueError):
            print(f"[!] Ignoring unusable OCR_ALLOWED_DIRS entry: {_extra}")

ALLOWED_UPLOAD_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
MAX_UPLOAD_BYTES = 256 * 1024 * 1024  # 256 MB
DOCS_CACHE_TTL = 2.0  # seconds

# --------------------------------------------------------------------------
# Path safety
# --------------------------------------------------------------------------


def safe_resolve(raw_path, roots=None):
    """Resolve raw_path and return it only if it sits inside an allowed root.

    Returns None for anything outside, so a caller can never be talked into
    reading arbitrary files off the machine.
    """
    if not raw_path:
        return None
    try:
        resolved = Path(raw_path).resolve()
    except (OSError, ValueError):
        return None
    for root in (roots if roots is not None else ALLOWED_ROOTS):
        try:
            if resolved == root or resolved.is_relative_to(root):
                return resolved
        except (OSError, ValueError):
            continue
    return None


def safe_int(value, default=0, minimum=None, maximum=None):
    """Parse an int from untrusted input without ever raising."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default
    if minimum is not None and parsed < minimum:
        return minimum
    if maximum is not None and parsed > maximum:
        return maximum
    return parsed


def sanitize_run_id(raw):
    """Strip a run id down to a single harmless path segment."""
    if not raw:
        return None
    cleaned = Path(urllib.parse.unquote(raw)).name
    if not cleaned or cleaned in (".", ".."):
        return None
    return cleaned


# --------------------------------------------------------------------------
# OCR engine (lazily built, guarded for the threaded server)
# --------------------------------------------------------------------------

_ocr_engine = None
_engine_lock = threading.Lock()   # guards construction
_predict_lock = threading.Lock()  # serializes inference; Paddle predictors
                                  # are not safe to share across threads


def get_ocr_engine():
    global _ocr_engine
    with _engine_lock:
        if _ocr_engine is None:
            from paddleocr import PaddleOCR
            _ocr_engine = PaddleOCR(
                text_detection_model_name="PP-OCRv6_medium_det",
                text_recognition_model_name="PP-OCRv6_medium_rec",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=False,
            )
        return _ocr_engine


def pdf_page_count(file_path):
    """Total pages in a PDF, or None if it cannot be determined."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(file_path))
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:
        return None


# --------------------------------------------------------------------------
# Output discovery
# --------------------------------------------------------------------------

_docs_cache = {"ts": 0.0, "data": None}
_docs_cache_lock = threading.Lock()


def invalidate_docs_cache():
    with _docs_cache_lock:
        _docs_cache["ts"] = 0.0
        _docs_cache["data"] = None


def find_image_for_run(run_id):
    """Annotated image for a run id, whichever extension Paddle wrote."""
    for ext in (".png", ".jpg", ".jpeg"):
        img_path = OUTPUT_DIR / f"{run_id}_ocr_res_img{ext}"
        if img_path.exists():
            return img_path
    return None


def _scan_document_groups():
    """Group every *_res.json in output/ into documents with ordered pages."""
    items_by_doc = {}

    for jf in OUTPUT_DIR.glob("*_res.json"):
        run_id = jf.stem[:-4] if jf.stem.endswith("_res") else jf.stem
        img_file = find_image_for_run(run_id)
        try:
            stat = jf.stat()
        except OSError:
            continue

        # input_path and page_index sit in the JSON header, so a short read
        # is enough - these files can be several MB each.
        page_idx = None
        input_path = None
        try:
            with open(jf, "r", encoding="utf-8") as f:
                head = f.read(1024)
            m_path = re.search(r'"input_path"\s*:\s*"((?:[^"\\]|\\.)*)"', head)
            m_page = re.search(r'"page_index"\s*:\s*(null|\d+)', head)
            if m_path:
                try:
                    input_path = json.loads(f'"{m_path.group(1)}"')
                except ValueError:
                    input_path = m_path.group(1).replace("\\\\", "\\")
            if m_page and m_page.group(1) != "null":
                page_idx = int(m_page.group(1))
        except (OSError, UnicodeDecodeError):
            pass

        if input_path:
            doc_id = Path(input_path).stem
        else:
            match = re.match(r"^(.*)_(\d+)$", run_id)
            if match:
                doc_id = match.group(1)
                if page_idx is None:
                    page_idx = int(match.group(2))
            else:
                doc_id = run_id
                if page_idx is None:
                    page_idx = 0

        doc = items_by_doc.get(doc_id)
        if doc is None:
            doc = items_by_doc[doc_id] = {
                "doc_id": doc_id,
                "input_path": input_path,
                "is_pdf": bool(input_path and input_path.lower().endswith(".pdf")),
                "latest_modified": stat.st_mtime,
                "pages": [],
            }

        if stat.st_mtime > doc["latest_modified"]:
            doc["latest_modified"] = stat.st_mtime
        if input_path and not doc["input_path"]:
            doc["input_path"] = input_path
            doc["is_pdf"] = input_path.lower().endswith(".pdf")

        doc["pages"].append({
            "run_id": run_id,
            "page_num": (page_idx + 1) if page_idx is not None else 1,
            "page_index": page_idx,
            "json_filename": jf.name,
            "has_image": img_file is not None,
            "image_filename": img_file.name if img_file else None,
            "modified_time": stat.st_mtime,
            "size_bytes": stat.st_size,
        })

    sorted_docs = sorted(items_by_doc.values(), key=lambda d: d["latest_modified"], reverse=True)
    for doc in sorted_docs:
        doc["pages"].sort(key=lambda p: p["page_num"] if p["page_num"] is not None else 9999)
        doc["total_pages"] = len(doc["pages"])
        doc["source_readable"] = safe_resolve(doc["input_path"]) is not None
    return sorted_docs


def get_all_document_groups():
    """Cached view of the output directory (TTL keeps repeat calls cheap)."""
    now = time.time()
    with _docs_cache_lock:
        if _docs_cache["data"] is not None and (now - _docs_cache["ts"]) < DOCS_CACHE_TTL:
            return _docs_cache["data"]
    data = _scan_document_groups()
    with _docs_cache_lock:
        _docs_cache["data"] = data
        _docs_cache["ts"] = time.time()
    return data


def _locate_page(run_id, docs):
    """Find (document, index) for a run id within an already-built doc list."""
    for doc in docs:
        for idx, page in enumerate(doc["pages"]):
            if page["run_id"] == run_id:
                return doc, idx
    return None, -1


def load_page_run_details(run_id, docs=None):
    """Full detail payload for one OCR'd page.

    Pass `docs` when calling in a loop - rebuilding the group list per page is
    what used to make the combined-document endpoint quadratic.
    """
    run_id = sanitize_run_id(run_id)
    if not run_id:
        return None

    json_file = OUTPUT_DIR / f"{run_id}_res.json"
    if not json_file.exists():
        return None

    try:
        with open(json_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except (OSError, ValueError) as e:
        return {"error": f"Failed to parse JSON file: {e}"}

    rec_texts = raw_data.get("rec_texts", []) or []
    rec_scores = raw_data.get("rec_scores", []) or []
    rec_polys = raw_data.get("rec_polys") or raw_data.get("dt_polys") or []

    lines = []
    for i, text in enumerate(rec_texts):
        score = None
        if i < len(rec_scores):
            try:
                score = round(float(rec_scores[i]) * 100, 2)
            except (TypeError, ValueError):
                score = None
        lines.append({
            "id": i + 1,
            "text": text,
            "score": score,
            "poly": rec_polys[i] if i < len(rec_polys) else None,
        })

    numeric_scores = [float(s) for s in rec_scores if isinstance(s, (int, float))]
    avg_score = round(sum(numeric_scores) / len(numeric_scores) * 100, 2) if numeric_scores else 0.0

    if docs is None:
        docs = get_all_document_groups()
    parent_doc, curr_idx = _locate_page(run_id, docs)

    page_num, total_pages = 1, 1
    prev_run_id = next_run_id = None
    doc_id = run_id
    if parent_doc:
        doc_id = parent_doc["doc_id"]
        total_pages = parent_doc["total_pages"]
        page_num = parent_doc["pages"][curr_idx]["page_num"]
        if curr_idx > 0:
            prev_run_id = parent_doc["pages"][curr_idx - 1]["run_id"]
        if curr_idx < len(parent_doc["pages"]) - 1:
            next_run_id = parent_doc["pages"][curr_idx + 1]["run_id"]

    img_file = find_image_for_run(run_id)
    input_path = raw_data.get("input_path")

    return {
        "id": run_id,
        "doc_id": doc_id,
        "page_num": page_num,
        "page_index": raw_data.get("page_index"),
        "total_pages": total_pages,
        "prev_run_id": prev_run_id,
        "next_run_id": next_run_id,
        "input_path": input_path,
        "source_readable": safe_resolve(input_path) is not None,
        "plain_text": "\n".join(rec_texts),
        "lines": lines,
        "stats": {
            "total_lines": len(rec_texts),
            "word_count": sum(len(t.split()) for t in rec_texts),
            "char_count": sum(len(t) for t in rec_texts),
            "avg_score": avg_score,
            "min_score": round(min(numeric_scores) * 100, 2) if numeric_scores else 0.0,
            "max_score": round(max(numeric_scores) * 100, 2) if numeric_scores else 0.0,
            "high_conf_count": sum(1 for s in numeric_scores if s >= 0.9),
            "med_conf_count": sum(1 for s in numeric_scores if 0.7 <= s < 0.9),
            "low_conf_count": sum(1 for s in numeric_scores if s < 0.7),
        },
        "annotated_image_url": f"/output/{img_file.name}" if img_file else None,
        "raw_json": raw_data,
    }


_structured_cache = {}
_structured_lock = threading.Lock()


def load_structured_report(doc_id):
    """The document as a structured report: its table, one object per row.

    Returns (payload, error, http_status).

    Built by the extraction pipeline, not from the OCR line list, and without
    running OCR again: each page this viewer has OCR'd is handed back to the
    pipeline as saved tokens. A PDF page with a usable text layer is still read
    from that layer rather than from OCR, so its figures come out exact rather
    than recognised (CLAUDE.md s4.1). That needs the source file itself, which
    is why a document whose source cannot be read gets an error rather than a
    report built on the weaker evidence.

    Cached per document until any of its pages is re-run.
    """
    docs = get_all_document_groups()
    doc = next((d for d in docs if d["doc_id"] == doc_id), None)
    if doc is None:
        return None, "Document not found", 404
    source = safe_resolve(doc["input_path"]) if doc["input_path"] else None
    if source is None or not source.is_file():
        return None, ("The source file for this document cannot be read, so a "
                      "structured report cannot be built. Set OCR_ALLOWED_DIRS to "
                      "include its folder."), 409

    stamp = doc["latest_modified"]
    with _structured_lock:
        hit = _structured_cache.get(doc_id)
        if hit and hit[0] == stamp:
            return hit[1], None, 200

    try:
        from pipeline import process_file
        from exporter import build_report
        from readers.ocr_reader import tokens_from_result

        tokens = {}
        for page in doc["pages"]:
            with open(OUTPUT_DIR / page["json_filename"], "r", encoding="utf-8") as f:
                raw = json.load(f)
            index = page["page_index"] if page["page_index"] is not None else 0
            tokens[index] = tokens_from_result(raw.get("res", raw))

        started = time.perf_counter()
        result = process_file(source, pages=sorted(tokens), ocr_tokens=tokens)
        report = build_report(result)
        report["source"]["built_in_seconds"] = round(time.perf_counter() - started, 2)
    except Exception as exc:
        traceback.print_exc()
        return None, f"Could not build the structured report: {type(exc).__name__}: {exc}", 500

    with _structured_lock:
        _structured_cache[doc_id] = (stamp, report)
    return report, None, 200


def load_combined_document(doc_id):
    """Every page of a document flattened into one payload."""
    docs = get_all_document_groups()
    target_doc = next((d for d in docs if d["doc_id"] == doc_id), None)
    if not target_doc:
        return None

    combined_lines = []
    text_parts = []
    page_summaries = []
    total_words = total_chars = 0
    all_scores = []
    first_page = None

    for page in target_doc["pages"]:
        details = load_page_run_details(page["run_id"], docs=docs)
        if not details or "error" in details:
            continue
        if first_page is None:
            first_page = details

        page_num = page["page_num"]
        text_parts.append(f"=== PAGE {page_num} ===\n{details['plain_text']}\n")

        for line in details["lines"]:
            combined_lines.append({
                "page": page_num,
                "id": len(combined_lines) + 1,
                "page_line_id": line["id"],
                "run_id": page["run_id"],
                "text": line["text"],
                "score": line["score"],
                "poly": line["poly"],
            })
            if line["score"] is not None:
                all_scores.append(line["score"])

        total_words += details["stats"]["word_count"]
        total_chars += details["stats"]["char_count"]
        page_summaries.append({
            "page_num": page_num,
            "run_id": page["run_id"],
            "line_count": details["stats"]["total_lines"],
            "avg_score": details["stats"]["avg_score"],
        })

    return {
        "doc_id": doc_id,
        "input_path": target_doc["input_path"],
        "source_readable": target_doc["source_readable"],
        "total_pages": target_doc["total_pages"],
        "plain_text": "\n".join(text_parts),
        "lines": combined_lines,
        "stats": {
            "total_lines": len(combined_lines),
            "word_count": total_words,
            "char_count": total_chars,
            "avg_score": round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0,
            "high_conf_count": sum(1 for s in all_scores if s >= 90),
            "med_conf_count": sum(1 for s in all_scores if 70 <= s < 90),
            "low_conf_count": sum(1 for s in all_scores if s < 70),
            "pages_count": len(page_summaries),
        },
        "pages": page_summaries,
        "first_page": {
            "run_id": first_page["id"],
            "page_index": first_page["page_index"],
            "annotated_image_url": first_page["annotated_image_url"],
            "lines": first_page["lines"],
        } if first_page else None,
    }


# --------------------------------------------------------------------------
# Background OCR jobs
# --------------------------------------------------------------------------

_jobs = {}
_jobs_lock = threading.Lock()
MAX_JOB_HISTORY = 40


def _update_job(job_id, **fields):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.update(fields)


def _create_job(file_path, page_mode, start_page, end_page):
    job_id = uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "status": "queued",
        "file_path": str(file_path),
        "filename": Path(file_path).name,
        "page_mode": page_mode,
        "start_page": start_page,
        "end_page": end_page,
        "pages_done": 0,
        "pages_expected": None,
        "pages": [],
        "first_run_id": None,
        "message": "Queued - waiting for the OCR engine",
        "error": None,
        "started_at": time.time(),
        "finished_at": None,
    }
    with _jobs_lock:
        _jobs[job_id] = job
        if len(_jobs) > MAX_JOB_HISTORY:
            done = sorted(
                (j for j in _jobs.values() if j["finished_at"]),
                key=lambda j: j["finished_at"],
            )
            for stale in done[: len(_jobs) - MAX_JOB_HISTORY]:
                _jobs.pop(stale["job_id"], None)
    return job_id


def _run_ocr_job(job_id, file_path, page_mode, start_page, end_page):
    """Worker body: OCR the file, saving and reporting each page as it lands."""
    is_pdf = file_path.suffix.lower() == ".pdf"
    stem = file_path.stem

    try:
        if is_pdf:
            total = pdf_page_count(file_path)
            if total:
                if page_mode == "first":
                    expected = 1
                elif page_mode == "range":
                    expected = max(0, min(end_page, total) - start_page + 1)
                else:
                    expected = total
                _update_job(job_id, pages_expected=expected, pdf_total_pages=total)

        _update_job(job_id, status="loading", message="Loading PaddleOCR models (first run takes a while)")
        engine = get_ocr_engine()

        _update_job(job_id, status="running", message="Running text detection and recognition")

        saved = []
        # One inference at a time - the predictor is shared process-wide.
        with _predict_lock:
            for page_idx, page_res in enumerate(engine.predict(str(file_path)), start=1):
                if is_pdf:
                    if page_mode == "first" and page_idx > 1:
                        break
                    if page_mode == "range":
                        if page_idx > end_page:
                            break
                        if page_idx < start_page:
                            continue

                page_res.save_to_json(str(OUTPUT_DIR))
                page_res.save_to_img(str(OUTPUT_DIR))

                run_id = f"{stem}_{page_idx - 1}" if is_pdf else stem
                saved.append({"page_num": page_idx, "run_id": run_id})
                invalidate_docs_cache()

                with _jobs_lock:
                    job = _jobs.get(job_id)
                    if job is not None:
                        job["pages_done"] = len(saved)
                        job["pages"] = list(saved)
                        job["message"] = f"Saved page {page_idx}"
                        if job["first_run_id"] is None:
                            job["first_run_id"] = run_id

        invalidate_docs_cache()
        _update_job(
            job_id,
            status="done",
            message=f"Finished - {len(saved)} page(s) processed",
            finished_at=time.time(),
        )
    except Exception as e:
        traceback.print_exc()
        invalidate_docs_cache()
        _update_job(
            job_id,
            status="error",
            error=f"{type(e).__name__}: {e}",
            message="OCR failed",
            finished_at=time.time(),
        )


def start_ocr_job(file_path, page_mode, start_page, end_page):
    job_id = _create_job(file_path, page_mode, start_page, end_page)
    worker = threading.Thread(
        target=_run_ocr_job,
        args=(job_id, file_path, page_mode, start_page, end_page),
        name=f"ocr-job-{job_id}",
        daemon=True,
    )
    worker.start()
    return job_id


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class OCRViewerHandler(BaseHTTPRequestHandler):
    server_version = "PaddleOCRStudio/2.0"
    protocol_version = "HTTP/1.1"

    # -- helpers ----------------------------------------------------------

    def _base_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._base_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message, status=400):
        self.send_json({"error": message}, status=status)

    def host_is_local(self):
        """Reject DNS-rebinding style requests aimed at a non-local hostname."""
        host = (self.headers.get("Host") or "").split(":")[0].strip("[]").lower()
        return host in ("", "localhost", "127.0.0.1", "::1", "0.0.0.0")

    def serve_file(self, file_path, content_type=None):
        file_path = Path(file_path)
        if content_type is None:
            content_type, _ = mimetypes.guess_type(str(file_path))
            content_type = content_type or "application/octet-stream"
        try:
            size = file_path.stat().st_size
            with open(file_path, "rb") as f:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-cache")
                self._base_headers()
                self.end_headers()
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except OSError as e:
            self.send_error_json(f"Failed to read file: {e}", 500)

    # -- routing ----------------------------------------------------------

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self._base_headers()
        self.end_headers()

    def do_GET(self):
        try:
            self._route_get()
        except Exception as e:
            traceback.print_exc()
            try:
                self.send_error_json(f"Internal server error: {type(e).__name__}: {e}", 500)
            except OSError:
                pass

    def do_POST(self):
        try:
            self._route_post()
        except Exception as e:
            traceback.print_exc()
            try:
                self.send_error_json(f"Internal server error: {type(e).__name__}: {e}", 500)
            except OSError:
                pass

    def _route_get(self):
        if not self.host_is_local():
            self.send_error_json("Host not allowed", 403)
            return

        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/health":
            with _jobs_lock:
                active = sum(1 for j in _jobs.values() if j["status"] in ("queued", "loading", "running"))
            self.send_json({
                "status": "ok",
                "engine_loaded": _ocr_engine is not None,
                "active_jobs": active,
                "allowed_roots": [str(r) for r in ALLOWED_ROOTS],
            })
            return

        if path in ("/api/outputs", "/api/documents"):
            self.send_json({"documents": get_all_document_groups()})
            return

        if path.startswith("/api/output/"):
            run_id = sanitize_run_id(path[len("/api/output/"):])
            details = load_page_run_details(run_id) if run_id else None
            if details is None:
                self.send_error_json("Run not found", 404)
            else:
                self.send_json(details)
            return

        if path.startswith("/api/document-combined/"):
            doc_id = path[len("/api/document-combined/"):]
            combined = load_combined_document(doc_id)
            if combined is None:
                self.send_error_json("Document not found", 404)
            else:
                self.send_json(combined)
            return

        if path.startswith("/api/structured/"):
            doc_id = path[len("/api/structured/"):]
            report, error, status = load_structured_report(doc_id)
            if error:
                self.send_error_json(error, status)
            else:
                self.send_json(report)
            return

        if path.startswith("/api/job/"):
            job_id = sanitize_run_id(path[len("/api/job/"):])
            with _jobs_lock:
                job = dict(_jobs[job_id]) if job_id in _jobs else None
            if job is None:
                self.send_error_json("Job not found", 404)
            else:
                self.send_json(job)
            return

        if path == "/api/pdf-page-image":
            self._serve_pdf_page(query)
            return

        if path == "/api/raw-image":
            target = safe_resolve(query.get("path", [None])[0])
            if target is None:
                self.send_error_json(
                    "Path is outside the allowed folders. Set OCR_ALLOWED_DIRS to permit it.", 403)
                return
            if not target.is_file():
                self.send_error_json("Image not found", 404)
                return
            self.serve_file(target)
            return

        if path.startswith("/output/"):
            target = safe_resolve(OUTPUT_DIR / path[len("/output/"):], roots=[OUTPUT_DIR])
            if target is None or not target.is_file():
                self.send_error_json("File not found in output", 404)
                return
            self.serve_file(target)
            return

        # Static web assets
        if path in ("/", "/index.html"):
            target = WEB_DIR / "index.html"
        else:
            target = safe_resolve(WEB_DIR / path.lstrip("/"), roots=[WEB_DIR])

        if target is not None and Path(target).is_file():
            self.serve_file(target)
        else:
            self.send_error_json("Not Found", 404)

    def _serve_pdf_page(self, query):
        target = safe_resolve(query.get("path", [None])[0])
        if target is None:
            self.send_error_json(
                "Path is outside the allowed folders. Set OCR_ALLOWED_DIRS to permit it.", 403)
            return
        if not target.is_file():
            self.send_error_json("File not found", 404)
            return

        page_idx = safe_int(query.get("page", ["0"])[0], default=0, minimum=0)
        scale = max(0.5, min(4.0, float(safe_int(query.get("scale", ["20"])[0], default=20, minimum=5, maximum=40)) / 10.0))

        try:
            import pypdfium2 as pdfium
        except ImportError:
            self.send_error_json("pypdfium2 is not installed - run: pip install -r requirements.txt", 500)
            return

        doc = None
        try:
            doc = pdfium.PdfDocument(str(target))
            if page_idx >= len(doc):
                self.send_error_json(f"Page index {page_idx} out of range (document has {len(doc)})", 400)
                return
            image = doc[page_idx].render(scale=scale).to_pil()
        except Exception as e:
            self.send_error_json(f"Failed to render PDF page: {type(e).__name__}: {e}", 500)
            return
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=90)
        jpeg_bytes = buf.getvalue()

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg_bytes)))
        self.send_header("Cache-Control", "no-cache")
        self._base_headers()
        self.end_headers()
        self.wfile.write(jpeg_bytes)

    def _route_post(self):
        if not self.host_is_local():
            self.send_error_json("Host not allowed", 403)
            return

        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path == "/api/upload":
            self._handle_upload(parsed)
            return
        if path == "/api/run-ocr":
            self._handle_run_ocr()
            return

        self.send_error_json("Endpoint not found", 404)

    def _handle_upload(self, parsed):
        content_length = safe_int(self.headers.get("Content-Length"), default=0, minimum=0)
        if content_length <= 0:
            self.send_error_json("No file content uploaded", 400)
            return
        if content_length > MAX_UPLOAD_BYTES:
            self.send_error_json(
                f"File is too large ({content_length / 1048576:.1f} MB). "
                f"Limit is {MAX_UPLOAD_BYTES // 1048576} MB.", 413)
            return

        query = urllib.parse.parse_qs(parsed.query)
        raw_name = query.get("filename", [None])[0] or self.headers.get("X-Filename")
        if raw_name:
            filename = Path(urllib.parse.unquote(raw_name)).name
        else:
            filename = f"upload_{int(time.time())}.pdf"
        if not filename or filename in (".", ".."):
            filename = f"upload_{int(time.time())}.pdf"

        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            self.send_error_json(
                f"Unsupported file type '{suffix or 'none'}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_UPLOAD_SUFFIXES))}", 415)
            return

        upload_path = UPLOADS_DIR / filename
        # Never silently clobber an earlier upload of the same name.
        if upload_path.exists():
            upload_path = UPLOADS_DIR / f"{Path(filename).stem}_{int(time.time())}{suffix}"

        written = 0
        try:
            with open(upload_path, "wb") as f:
                while written < content_length:
                    chunk = self.rfile.read(min(content_length - written, 64 * 1024))
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
        except OSError as e:
            self.send_error_json(f"Upload failed: {e}", 500)
            return

        if written < content_length:
            try:
                upload_path.unlink()
            except OSError:
                pass
            self.send_error_json("Upload was truncated - please try again", 400)
            return

        self.send_json({
            "success": True,
            "filename": upload_path.name,
            "filepath": str(upload_path.resolve()),
            "size_bytes": written,
        })

    def _handle_run_ocr(self):
        content_length = safe_int(self.headers.get("Content-Length"), default=0, minimum=0)
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length else {}
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
        except (ValueError, UnicodeDecodeError) as e:
            self.send_error_json(f"Invalid request payload: {e}", 400)
            return

        raw_path = payload.get("image_path")
        if not raw_path:
            self.send_error_json("image_path is required", 400)
            return

        target = safe_resolve(raw_path)
        if target is None:
            self.send_error_json(
                "That path is outside the allowed folders. Upload the file instead, "
                "or start the server with OCR_ALLOWED_DIRS set to its folder.", 403)
            return
        if not target.is_file():
            self.send_error_json(f"File not found on server: {target}", 404)
            return
        if target.suffix.lower() not in ALLOWED_UPLOAD_SUFFIXES:
            self.send_error_json(f"Unsupported file type '{target.suffix}'", 415)
            return

        page_mode = payload.get("page_mode", "first")
        if page_mode not in ("first", "range", "all"):
            page_mode = "first"
        start_page = safe_int(payload.get("start_page"), default=1, minimum=1)
        end_page = safe_int(payload.get("end_page"), default=start_page, minimum=1)
        if end_page < start_page:
            start_page, end_page = end_page, start_page

        job_id = start_ocr_job(target, page_mode, start_page, end_page)
        self.send_json({"success": True, "job_id": job_id, "filename": target.name}, status=202)

    def log_message(self, fmt, *args):
        sys.stdout.write("  %s  %s\n" % (time.strftime("%H:%M:%S"), fmt % args))
        sys.stdout.flush()


def run_server(host="127.0.0.1", port=8060):
    httpd = ThreadedHTTPServer((host, port), OCRViewerHandler)
    print("=" * 62)
    print("  PaddleOCR Studio")
    print("=" * 62)
    print(f"  URL          http://{'localhost' if host == '127.0.0.1' else host}:{port}")
    print(f"  Web UI       {WEB_DIR}")
    print(f"  Results      {OUTPUT_DIR}")
    print(f"  Uploads      {UPLOADS_DIR}")
    print(f"  Readable     {', '.join(str(r) for r in ALLOWED_ROOTS)}")
    print("=" * 62)
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
    finally:
        httpd.server_close()


def main():
    parser = argparse.ArgumentParser(description="PaddleOCR Studio server")
    parser.add_argument("port", nargs="?", type=int, default=8060, help="port to listen on (default: 8060)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="interface to bind (default: 127.0.0.1, local only)")
    args = parser.parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
