# `linecaster.page/3` fixtures

Two pages of a fake item (`library.test_item1`), written by hand to the data model's specification
(`docs/reference/data-model.md`); every name and text is invented.

| Case | Where |
|---|---|
| a ground truth's provenance: people, their review per page | `ground_truth.annotators[0]` (`validated` on page 12, `proofread` on 13), `source` |
| a running head with a title part and a page-number part | page 12: `r1` (role `header`), `r1a` and `r1b` (`parent` `r1`, role `page_number`) |
| a misprint and its correction; the reading keeps what is printed | page 12: the `corrected` edit on `l3` |
| an illegible character | page 12: U+FFFD in `l4`, `status` `illegible` |
| a footnote without a box, and its mark in the text | page 12: `r3` (role `footnote`), the `note_of` link to the mark's span |
| a word divided across lines, and across pages | page 12: the `joined` edits on `l4` and `l5` (the second names `library.test_item1_0013#l1[0:3]`) |
| a paragraph continued on the next page | range `s12.r2.p1` on both pages |
| a model's output for the same page: raw output, boxes, roles from its labels, a figure's description | page 12: `ocr_new` |
