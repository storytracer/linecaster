linecaster's document (`linecaster.document`) of a page or an item, in reading order, its paragraphs linked across
page breaks. Each region is a block by its content role: titles and headings at their levels, paragraphs, list
items, captions, notes, and page headers and footers in the furniture layer. Text regions come from their paragraphs
when a recomposition made them, else as laid out, one row per line. A paragraph or region that continues another
(its `continues` link) is one block with it, on a new row: the text stays as read (a strategy's `flow` joins the
rows, `unicode-marks` or a source's divided words resolve a mark at the join). Tables follow the rendering
policy's table rules, formulas keep their LaTeX, and pictures their image and the text read inside them.

- `sections` false: no sections. With it, every title or heading opens a section that holds every block up to the
  next one (in the JSON, `Block.section`; HTML, Markdown and text read the same).
