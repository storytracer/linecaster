"""Byte comparison of linecaster's per-page md/txt exports (``PageExportsWriter`` with suffix
``.paddle`` and ``furniture=True``) with squiddleocr's goldens (``--text lines --furniture``); for
differing pages a short diff.

    python compare_exports.py EXPORTS_DIR GOLDEN_DIR [--show N] [--no-nfc]

Both sides are NFC-normalised before comparing (squiddleocr wrote kraken's decomposed text; linecaster's
as-written layer is NFC after ``UnicodeNormalizer``), so parity means "byte-exact after NFC";
``--no-nfc`` compares the raw bytes.
"""
import difflib
import glob
import os
import sys
import unicodedata

ours, gold = sys.argv[1], sys.argv[2]
show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 0
nfc = (lambda s: s) if "--no-nfc" in sys.argv else (lambda s: unicodedata.normalize("NFC", s))
for ext in ("txt", "md"):
    same, diff = [], []
    for g in sorted(glob.glob(f"{gold}/*.paddle.{ext}")):
        o = os.path.join(ours, os.path.basename(g))
        a = nfc(open(g, encoding="utf-8").read())
        b = nfc(open(o, encoding="utf-8").read()) if os.path.exists(o) else None
        (same if a == b else diff).append((os.path.basename(g), a, b))
    print(f"{ext}: {len(same)}/{len(same) + len(diff)} identical; differ: {[d[0].split('.')[0] for d in diff]}")
    for name, a, b in diff[:show]:
        print(f"--- {name}")
        for l in list(difflib.unified_diff(a.splitlines(), (b or "").splitlines(), "golden", "linecaster", lineterm="", n=0))[2:14]:
            print("   ", l[:150])
