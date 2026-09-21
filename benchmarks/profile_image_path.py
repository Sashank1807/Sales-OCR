"""Where the time goes on a scanned page.

One benchmark page took 519 seconds and another 132. At that rate the 31
scanned PDFs in the corpus are an overnight job, so the first question is which
stage is actually responsible - rendering, detection, recognition or geometry.

This measures; it does not optimise.

    python profile_image_path.py                     # the default sample
    python profile_image_path.py page.pdf --page 3
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")

CORPUS = Path("D:/OCR_testing/SS")
DEFAULT_SAMPLE: tuple[tuple[str, int], ...] = (
    ("02_2060543_140_20260819095307562.PDF", 2),
    ("02_2060116_140_20260819102230276.pdf", 0),
)


@dataclass
class Stage:
    name: str
    seconds: float
    detail: str = ""


@dataclass
class PageProfile:
    source: str
    page_index: int
    stages: list[Stage] = field(default_factory=list)
    pixels: int = 0
    tokens: int = 0
    device: str = "unknown"

    @property
    def total(self) -> float:
        return sum(s.seconds for s in self.stages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "page_index": self.page_index,
            "device": self.device, "pixels": self.pixels, "tokens": self.tokens,
            "total_seconds": round(self.total, 2),
            "stages": [{"name": s.name, "seconds": round(s.seconds, 2),
                        "share": round(s.seconds / self.total, 3) if self.total else 0.0,
                        "detail": s.detail} for s in self.stages],
        }


def detect_device() -> str:
    """Whether Paddle will run on a GPU or the CPU.

    Worth stating explicitly: a 500-second page means something very different
    on a CPU than on an RTX 2000 that is sitting idle because the wheel
    installed was the CPU build.
    """
    try:
        import paddle
    except ImportError:
        return "paddle not importable"
    try:
        compiled = bool(paddle.device.is_compiled_with_cuda())
    except Exception:
        compiled = False
    if not compiled:
        return "CPU (paddlepaddle built without CUDA)"
    try:
        count = paddle.device.cuda.device_count()
    except Exception:
        count = 0
    if not count:
        return "CPU (CUDA build, no device visible)"
    try:
        name = paddle.device.cuda.get_device_properties(0).name
    except Exception:
        name = "unknown GPU"
    return f"GPU ({name}, {count} device(s))"


def profile_page(path: Path, page_index: int = 0,
                 scale: float = 2.0) -> PageProfile:
    from readers import ocr_reader
    from readers.geometry import build_grid

    profile = PageProfile(source=path.name, page_index=page_index,
                          device=detect_device())

    # -- model load, paid once per process ------------------------------
    started = time.perf_counter()
    engine = ocr_reader.get_engine()
    profile.stages.append(Stage("engine load", time.perf_counter() - started,
                                "once per process, not per page"))

    # -- rasterise ------------------------------------------------------
    started = time.perf_counter()
    if path.suffix.lower() == ".pdf":
        import numpy as np
        import pymupdf
        with pymupdf.open(str(path)) as doc:
            pixmap = doc[page_index].get_pixmap(matrix=pymupdf.Matrix(scale, scale))
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width, pixmap.n)
            if pixmap.n == 4:
                image = image[:, :, :3]
            image = np.ascontiguousarray(image[:, :, ::-1])
        target: Any = image
        profile.pixels = image.shape[0] * image.shape[1]
        detail = f"{image.shape[1]}x{image.shape[0]} at scale {scale}"
    else:
        target = str(path)
        try:
            from PIL import Image
            with Image.open(path) as handle:
                profile.pixels = handle.width * handle.height
                detail = f"{handle.width}x{handle.height}"
        except Exception:
            detail = "image file"
    profile.stages.append(Stage("rasterise", time.perf_counter() - started, detail))

    # -- recognition ----------------------------------------------------
    # PaddleOCR's predict() runs detection and recognition behind one call, so
    # they cannot be separated without reaching inside it. Reported together
    # and labelled as such rather than split on a guess.
    started = time.perf_counter()
    results = list(engine.predict(target))
    profile.stages.append(Stage("paddleocr detect+recognise",
                                time.perf_counter() - started,
                                "one call; the two stages are not separable "
                                "from outside predict()"))

    # -- tokens ---------------------------------------------------------
    started = time.perf_counter()
    tokens = ocr_reader.tokens_from_result(results[0]) if results else []
    profile.tokens = len(tokens)
    profile.stages.append(Stage("token extraction", time.perf_counter() - started,
                                f"{len(tokens)} token(s)"))

    # -- geometry -------------------------------------------------------
    started = time.perf_counter()
    build_grid(tokens, page=page_index + 1, source="ocr", origin=str(path))
    profile.stages.append(Stage("geometry", time.perf_counter() - started,
                                "clustering, bands, cell assignment"))
    return profile


def format_report(profiles: Sequence[PageProfile]) -> str:
    lines: list[str] = []
    if profiles:
        lines.append(f"device: {profiles[0].device}")
        lines.append("")
    for profile in profiles:
        lines.append(f"{profile.source} page {profile.page_index + 1}  "
                     f"{profile.pixels / 1e6:.1f} MPix  "
                     f"{profile.tokens} tokens  total {profile.total:.1f}s")
        for stage in profile.stages:
            share = stage.seconds / profile.total if profile.total else 0.0
            bar = "#" * max(0, int(share * 40))
            lines.append(f"   {stage.name:<28} {stage.seconds:>7.2f}s "
                         f"{share:>6.1%} {bar}")
            if stage.detail:
                lines.append(f"      {stage.detail}")
        lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile the OCR path")
    parser.add_argument("path", nargs="?")
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.path:
        targets = [(Path(args.path), args.page)]
    else:
        targets = [(CORPUS / name, index) for name, index in DEFAULT_SAMPLE]

    profiles = []
    for path, index in targets:
        if not path.is_file():
            print(f"skipping {path}: not found", file=sys.stderr)
            continue
        print(f"profiling {path.name} page {index + 1} ...", file=sys.stderr, flush=True)
        profiles.append(profile_page(path, index))

    if args.json:
        import json
        print(json.dumps([p.to_dict() for p in profiles], indent=2))
    else:
        print(format_report(profiles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
