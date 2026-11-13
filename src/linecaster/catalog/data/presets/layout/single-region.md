No layout analysis: the whole page is one region (id `page`, label `text`, classified as a paragraph), alone in its
reading order, so a line step on the whole page and the line assignment put every line into it. For plain OCR of pages without columns, tables or formulas
; with this layout there are no table or formula regions for `--tables` and
`--formulas` to read. Built in, no model, in the pipeline's process only.

- `label` `text`: the region's label, which also gives its content role.
- `region_id` `page`: the region's id.
