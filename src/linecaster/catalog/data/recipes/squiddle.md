SquiddleOCR's combination: fast OCR for historical print from small models. PP-DocLayoutV3 finds the regions
and their reading order, PP-OCRv6 medium detection finds the lines on the whole page, kraken's PP-OCRv6 medium
recognizer reads them (batch 8, bf16 on CUDA), SLANet_plus rebuilds tables and PP-FormulaNet_plus-L reads
formulas as LaTeX; squiddleocr's rule-based steps make the typography, recompose the text into paragraphs
(`ratios`, `unicode-recomposition`) and compose the page document (`docling-composition`); the readable item texts
(`--item-texts`) are normalized with `latin-historic`.

- The settings squiddleocr 0.3 shipped and its goldens were recorded with; the modular pipeline reproduces those goldens
  line for line (see the evidence).
- The recomposition is `squiddle ocr`'s default (its `--text reflow`); the goldens compare lines, which it does not
  change.
- Until phase 3 of the refactoring the recipe named the rule-based steps through the option `text: reflow`; naming
  their presets changes neither the pipeline nor its outputs, so the edition was migrated (its earlier hashes stay
  in the lock as `previous_sha256`), not renumbered.
- `squiddle ocr` runs this recipe when its model options are left at their defaults; with other models it is a
  variation, not the recipe.
