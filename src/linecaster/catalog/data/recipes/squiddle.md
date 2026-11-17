OCR for historical print from small models. PP-DocLayoutV3 finds the regions
and their reading order, PP-OCRv6 medium detection finds the lines on the whole page, kraken's PP-OCRv6 medium
recognizer reads them (batch 8, bf16 on CUDA), SLANet_plus rebuilds tables and PP-FormulaNet_plus-L reads
formulas as LaTeX; rule-based steps make the typography, recompose the text into paragraphs
(`ratios`, `unicode-paragraphs`) and compose the page document (`linked-document`). The item texts
(`--item-texts`) are two: the item as read (`literal:txt`) and a normalized one
(`latin-historic+unicode-marks+flow:md`: the historic letter forms modernized, the division marks no source marks
resolved by squiddleocr's rule with the item's words as its lexicon, the rows flowed into paragraphs).

- The recomposition changes paragraphs, not lines: a comparison of the lines is the same with or without it.
- The normalized text is the recipe's opinion: `unicode-marks` joins most words divided at a line end rightly, but
  also many compounds divided at their own hyphen (on Wikisource's page-break words: 94.5 % of 345 compounds without
  a lexicon). Name the texts with `--text` for others; the literal text is always the transcription as read.
- Edition 2 composes the page document with linecaster's own document (`linked-document`) instead of Docling's:
  the HTML, Markdown, text and JSON files differ, the transcriptions do not.
- A derivative that runs this recipe with other models runs a variation, not the recipe.
