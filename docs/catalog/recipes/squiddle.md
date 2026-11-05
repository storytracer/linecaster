# squiddle

*Recipe · edition 1 · pipeline [`transcribe_modular.v1`](../pipelines/transcribe_modular.v1.md) · core*

SquiddleOCR's combination: fast OCR for historical print from small models. PP-DocLayoutV3 finds the regions
and their reading order, PP-OCRv6 medium detection finds the lines on the whole page, kraken's PP-OCRv6 medium
recogniser reads them (batch 8, bf16 on CUDA), SLANet_plus rebuilds tables and PP-FormulaNet_plus-L reads
formulas as LaTeX; the text is reflowed into paragraphs.

- The settings squiddleocr 0.3 shipped and its goldens were recorded with; the modular pipeline reproduces those goldens
  line for line (see the evidence).
- `text: reflow` is `squiddle ocr`'s default; the goldens compare lines, which the text mode does not change.
- `squiddle ocr` runs this recipe when its model options are left at their defaults; with other models it is a
  variation, not the recipe.

```bash
uv run launch.py squiddle IMAGES OUT
```

| Slot | Preset |
|---|---|
| layout | [`pp-doclayoutv3@1`](../presets/layout/pp-doclayoutv3.md) |
| lines | [`pp-ocrv6-medium-det@1`](../presets/lines/pp-ocrv6-medium-det.md) |
| recognition | [`kraken-ppocrv6-medium@1`](../presets/recognition/kraken-ppocrv6-medium.md) |
| tables | [`slanet-plus@2`](../presets/tables/slanet-plus.md) |
| formulas | [`pp-formulanet-plus-l@1`](../presets/formulas/pp-formulanet-plus-l.md) |

| Option | Value |
|---|---|
| text | `reflow` |

## Evidence

| Date | Source | Dataset | Result |
|---|---|---|---|
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | lines_identical 1560, lines_total 1560, pages_exact 60 |
| 2026-11-03 | Linecaster run | finebooks/bhl-ocr-eval-sample-60@41ff347552d13967c5d3001ca3eada800b0c22d7 | lines_identical 1560, lines_total 1560, pages_exact 60 |
| 2026-11-03 | Linecaster run | bhl-ocr-eval-tables-7 | lines_identical 651, lines_total 651, pages_exact 7 |
| 2026-11-03 | Linecaster run | bhl-ocr-eval-tables-7 | lines_identical 651, lines_total 651, pages_exact 7 |

## Provenance

- storytracer/squiddleocr 0.3, the paddle pipeline's defaults (`squiddle legacy ocr --pipeline paddle`)
- storytracer/squiddleocr@7c8a052 (the goldens: sample-60, tables-7)
