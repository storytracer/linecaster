A DoclingDocument per page or item, in reading order. Titles and section headers become
headings at the typographer's levels, text regions text items with Docling's labels (from their paragraphs when a
recomposition made them, else as laid out, one row per line), page headers and footers go into Docling's
furniture layer, tables keep their cells and spans, formulas their LaTeX, pictures the text read inside them.

- `sections` false: no section groups. With it, every heading opens a section that holds everything up to the
  next heading (JSON and DocLang gain the tree; Markdown and text read the same).
