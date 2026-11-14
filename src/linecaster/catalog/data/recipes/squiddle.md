OCR for historical print from small models. PP-DocLayoutV3 finds the regions
and their reading order, PP-OCRv6 medium detection finds the lines on the whole page, kraken's PP-OCRv6 medium
recognizer reads them (batch 8, bf16 on CUDA), SLANet_plus rebuilds tables and PP-FormulaNet_plus-L reads
formulas as LaTeX; rule-based steps make the typography, recompose the text into paragraphs
(`ratios`, `unicode-recomposition`) and compose the page document (`linked-composition`); the readable item texts
(`--item-texts`) are normalized with `latin-historic`.

- The recomposition changes paragraphs, not lines: a comparison of the lines is the same with or without it.
- Edition 2 composes the page document with linecaster's own document (`linked-composition`) instead of Docling's:
  the HTML, Markdown, text and JSON files differ, the transcriptions do not.
- A derivative that runs this recipe with other models runs a variation, not the recipe.
