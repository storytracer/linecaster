"""Compare a linecaster run (page-row JSONL) with squiddleocr goldens (hOCR) line by line.

    python compare_goldens.py RUN_DIR GOLDEN_DIR [--transcription ocr] [--no-nfc]

The goldens' word texts are NFC-normalised first (squiddleocr wrote kraken's decomposed text; linecaster
normalises with UnicodeNormalizer), so parity means "byte-exact after NFC"; --no-nfc compares raw text.

Per page and in total: lines present in both (by id), line boxes equal (kraken's integer clip of the
polygon), word sequences equal (text and box), and the ids only one side has.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import re
import sys
import unicodedata
from pathlib import Path

from lxml import html

BBOX = re.compile(r"bbox (\d+) (\d+) (\d+) (\d+)")


def golden(path: Path, nfc: bool = True) -> dict:
    doc = html.parse(str(path))
    out = {}
    for ln in doc.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' ocr_line ') or contains(@class,'ocr_header') or contains(@class,'ocr_caption') or contains(@class,'ocr_textfloat')]"):
        box = tuple(int(v) for v in BBOX.search(ln.get("title")).groups())
        words = [(unicodedata.normalize("NFC", w.text_content()) if nfc else w.text_content(), tuple(int(v) for v in BBOX.search(w.get("title")).groups()))
                 for w in ln.xpath(".//*[contains(@class,'ocrx_word')]") if w.text_content().strip()]
        out[ln.get("id")] = (box, words)
    return out


def ours(row: dict, transcription: str, width: int, height: int) -> dict:
    import numpy as np

    out = {}
    for ln in row["page"]["transcriptions"][transcription]["lines"]:
        pts = np.rint(np.asarray(ln["polygon"], dtype=float)).astype(int)
        x0, y0 = int(np.clip(pts[:, 0].min(), 0, width - 1)), int(np.clip(pts[:, 1].min(), 0, height - 1))
        x1, y1 = int(np.clip(pts[:, 0].max(), 0, width - 1)), int(np.clip(pts[:, 1].max(), 0, height - 1))
        words = [(w["text"], (int(w["bbox"][0]), int(w["bbox"][1]), int(round(w["bbox"][0] + w["bbox"][2])),
                              int(round(w["bbox"][1] + w["bbox"][3])))) for w in ln["words"]]
        out[ln["id"]] = ((x0, y0, x1, y1), words)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run"); ap.add_argument("goldens"); ap.add_argument("--transcription", default="ocr")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--no-nfc", action="store_true",
                    help="compare the goldens' raw text (default: NFC, as linecaster's UnicodeNormalizer writes it)")
    a = ap.parse_args()
    files = sorted(glob.glob(f"{a.run}/*.jsonl") + glob.glob(f"{a.run}/*.jsonl.gz"))
    rows = [json.loads(l) for f in files for l in (gzip.open(f, "rt") if f.endswith(".gz") else open(f))]
    tot = dict(pages=0, lines_gold=0, lines_ours=0, common=0, box=0, words=0, pages_exact=0)
    for row in sorted(rows, key=lambda r: r["id"]):
        g = golden(next(Path(a.goldens).glob(f"{row['id']}.*hocr")), nfc=not a.no_nfc)
        img = row["page"]["image"]
        o = ours(row, a.transcription, img["width"], img["height"])
        common = set(g) & set(o)
        box = sum(g[k][0] == o[k][0] for k in common)
        words = sum(g[k][1] == o[k][1] for k in common)
        exact = len(g) == len(o) == len(common) == box == words
        for k, v in (("pages", 1), ("lines_gold", len(g)), ("lines_ours", len(o)), ("common", len(common)), ("box", box),
                     ("words", words), ("pages_exact", int(exact))):
            tot[k] += v
        if not exact and a.verbose:
            print(f"{row['id']}: gold {len(g)} ours {len(o)} common {len(common)} box {box} words {words}"
                  f" only-gold {sorted(set(g) - set(o))[:5]} only-ours {sorted(set(o) - set(g))[:5]}")
            for k in sorted(common):
                if g[k] != o[k]:
                    print("   ", k, g[k][0], o[k][0], [w[0] for w in g[k][1]][:6], [w[0] for w in o[k][1]][:6])
                    break
    print(json.dumps(tot))
    return 0 if tot["pages_exact"] == tot["pages"] else 1


if __name__ == "__main__":
    sys.exit(main())
