"""Read a scanned page or photograph with PaddleOCR.

Per-token confidence is carried through to the grid contract unflattened: it is
the only signal Stage B has for a text column, where no arithmetic can help,
and it is what catches the pen-marked cells on a phone photograph.

The engine is built once and guarded, because it is expensive to construct and
Paddle's predictors are not safe to share across threads.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Sequence

os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")

from .contract import Grid, Token
from .geometry import GeometryConfig, build_grid

__all__ = ["read_image", "read_pdf_page_ocr", "tokens_from_result", "get_engine"]

#: Rasterisation scale for PDF pages handed to OCR. 2.0 puts a 72 dpi page at
#: roughly 144 dpi.
#:
#: Measured on the GPU over the five benchmark image pages, against
#: PP-OCRv5_server: 2.0 gives 483 verified cells and 783 needing review, 3.0
#: gives 384/891 and also costs a page its health. Raising the scale reads
#: slightly *more* tokens but resolves fewer rows, so 2.0 stays - now because
#: it measures better, not because the extra pixels were too expensive to try.
#:
#: Note for anyone sweeping this: it is a default argument of
#: read_pdf_page_ocr, bound at import. Reassigning this module attribute alone
#: changes nothing and a sweep will silently re-measure the baseline.
PDF_RENDER_SCALE = 2.0

_engine = None
_engine_lock = threading.Lock()
_predict_lock = threading.Lock()


def get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            from paddleocr import PaddleOCR
            # PP-OCRv6_medium, measured over all 238 image-routed pages of JUNE
            # and the benchmark (CLAUDE.md s10 item 11): against PP-OCRv5_server
            # it verifies 5,542 cells to 5,339, flags 1,510 to 3,282, closes the
            # stock equation on 1,148 rows to 996 and is 17% faster; on the
            # user's transcribed photo, 108 cells verified correct to 0. v5
            # reads characters slightly better, but its boxes put figures in
            # the wrong columns; mixed det/rec pairs lose to both.
            _engine = PaddleOCR(
                text_detection_model_name="PP-OCRv6_medium_det",
                text_recognition_model_name="PP-OCRv6_medium_rec",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=False,
            )
        return _engine


def _poly_to_box(poly: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in poly]
    ys = [float(p[1]) for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def tokens_from_result(result: Any) -> list[Token]:
    """Turn one PaddleOCR page result into positioned tokens.

    Accepts either a result object or the plain dict its JSON form uses, so a
    previously saved ``*_res.json`` can be replayed without re-running the
    engine.
    """
    if hasattr(result, "get"):
        payload = result
    else:
        payload = getattr(result, "json", None) or {}
        payload = payload.get("res", payload) if isinstance(payload, dict) else {}

    texts = payload.get("rec_texts") or []
    scores = payload.get("rec_scores") or []
    polys = payload.get("rec_polys") or payload.get("dt_polys") or []

    tokens: list[Token] = []
    for i, text in enumerate(texts):
        text = str(text).strip()
        if not text:
            continue
        if i >= len(polys):
            continue
        x0, y0, x1, y1 = _poly_to_box(polys[i])
        try:
            confidence = float(scores[i]) if i < len(scores) else None
        except (TypeError, ValueError):
            confidence = None
        tokens.append(Token(text=text, x0=x0, y0=y0, x1=x1, y1=y1,
                            confidence=confidence if confidence is not None else 0.0,
                            index=len(tokens)))
    return tokens


def _predict(target: Any) -> list[Token]:
    engine = get_engine()
    with _predict_lock:                      # the predictor is process-wide
        results = list(engine.predict(target))
    if not results:
        return []
    return tokens_from_result(results[0])


#: Formats the OCR engine opens itself. Anything else is decoded here first.
_NATIVE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def _decode_image(path: Path) -> Any:
    """Hand the engine a path it can open, or pixels it does not have to.

    The engine decides what it can read by file extension, so a `.jfif` - a
    JPEG with a different name - and a `.heic` from an iPhone camera were both
    refused before a single pixel was looked at. Decoding them here keeps the
    router's per-extension list and the engine's in agreement. EXIF rotation is
    applied, since a phone records its orientation there rather than in the
    pixels.
    """
    if path.suffix.lower() in _NATIVE_IMAGE_SUFFIXES:
        return str(path)
    import numpy as np
    from PIL import Image, ImageOps
    if path.suffix.lower() in (".heic", ".heif"):
        try:
            from pillow_heif import register_heif_opener
        except ImportError as exc:        # say what is missing, not "cannot identify"
            raise RuntimeError(
                f"{path.name}: HEIC needs the pillow-heif package") from exc
        register_heif_opener()
    with Image.open(path) as image:
        rgb = ImageOps.exif_transpose(image).convert("RGB")
        return np.ascontiguousarray(np.asarray(rgb)[:, :, ::-1])   # RGB -> BGR


def read_image(path: str | Path, page: int = 1,
               config: GeometryConfig | None = None) -> Grid:
    """OCR an image file into the grid contract."""
    path = Path(path)
    tokens = _predict(_decode_image(path))
    grid = build_grid(tokens, page=page, source="ocr", origin=str(path),
                      page_label=path.stem, config=config)
    if not tokens:
        grid.notes.append("OCR returned no text")
    return grid


def read_pdf_page_ocr(path: str | Path, page_index: int = 0,
                      scale: float = PDF_RENDER_SCALE,
                      config: GeometryConfig | None = None) -> Grid:
    """Rasterise one PDF page and OCR it.

    Used for the scanned pages of a PDF that the router found to have no usable
    text layer - including pages inside a file whose other pages are native.
    """
    import numpy as np
    import pymupdf

    path = Path(path)
    with pymupdf.open(str(path)) as doc:
        if not 0 <= page_index < doc.page_count:
            raise IndexError(f"page {page_index} out of range for {path.name} "
                             f"({doc.page_count} pages)")
        pixmap = doc[page_index].get_pixmap(matrix=pymupdf.Matrix(scale, scale))
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height, pixmap.width, pixmap.n)
        if pixmap.n == 4:                    # RGBA -> RGB
            image = image[:, :, :3]
        image = np.ascontiguousarray(image[:, :, ::-1])   # RGB -> BGR for Paddle

    tokens = _predict(image)
    grid = build_grid(tokens, page=page_index + 1, source="ocr", origin=str(path),
                      page_label=f"p{page_index + 1}", config=config)
    grid.notes.append(f"rasterised at scale {scale} for OCR")
    if not tokens:
        grid.notes.append("OCR returned no text")
    return grid
