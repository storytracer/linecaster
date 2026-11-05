SquiddleOCR's combination: fast OCR for historical print from small models. PP-DocLayoutV3 finds the regions
and their reading order, PP-OCRv6 medium detection finds the lines on the whole page, kraken's PP-OCRv6 medium
recogniser reads them (batch 8, bf16 on CUDA), SLANet_plus rebuilds tables and PP-FormulaNet_plus-L reads
formulas as LaTeX; the text is reflowed into paragraphs.

- The settings squiddleocr 0.3 shipped and its goldens were recorded with; the modular pipeline reproduces those goldens
  line for line (see the evidence).
- `text: reflow` is `squiddle ocr`'s default; the goldens compare lines, which the text mode does not change.
- `squiddle ocr` runs this recipe when its model options are left at their defaults; with other models it is a
  variation, not the recipe.
