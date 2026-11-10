OCR for historical print from small models. PP-DocLayoutV3 finds the regions
and their reading order, PP-OCRv6 medium detection finds the lines on the whole page, kraken's PP-OCRv6 medium
recognizer reads them (batch 8, bf16 on CUDA), SLANet_plus rebuilds tables and PP-FormulaNet_plus-L reads
formulas as LaTeX; rule-based steps make the typography, recompose the text into paragraphs
(`ratios`, `unicode-recomposition`) and compose the page document (`docling-composition`); the readable item texts
(`--item-texts`) are normalized with `latin-historic`.

- The recomposition changes paragraphs, not lines: a comparison of the lines is the same with or without it.
- Until phase 3 of the refactoring the recipe named the rule-based steps through the option `text: reflow`; naming
  their presets changes neither the pipeline nor its outputs, so the edition was migrated (its earlier hashes stay
  in the lock as `previous_sha256`), not renumbered.
- A derivative that runs this recipe with other models runs a variation, not the recipe.
