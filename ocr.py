#!/usr/bin/env python3
"""OCR a single file from the command line.

    python ocr.py path/to/scan.pdf [output_dir]

Writes <stem>_res.json and <stem>_ocr_res_img.<ext> per page, in the same
layout the web UI reads. Run `python server.py` for the full interface.
"""

import os
import sys
from pathlib import Path

# Must be set before paddle is imported.
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    source = Path(sys.argv[1]).expanduser()
    if not source.is_file():
        print(f"[!] Not a file: {source}")
        return 1

    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    from paddleocr import PaddleOCR

    print(f"[*] Loading PP-OCRv6 medium models (first run downloads them)...")
    ocr = PaddleOCR(
        text_detection_model_name="PP-OCRv6_medium_det",
        text_recognition_model_name="PP-OCRv6_medium_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
    )

    print(f"[*] Reading {source}")
    pages = 0
    for page_num, result in enumerate(ocr.predict(str(source)), start=1):
        result.save_to_json(str(output_dir))
        result.save_to_img(str(output_dir))
        lines = len(result.get("rec_texts", []) or [])
        print(f"    page {page_num}: {lines} line(s) -> {output_dir}")
        pages += 1

    print(f"[*] Done - {pages} page(s) written to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
