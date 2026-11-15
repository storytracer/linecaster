The hierarchy of a page from its own type sizes, every rule a ratio to the body size (the
median row height of the page's text regions); the squiddle combination's typography.

- `levels`: a heading whose rows are at least 2.5 times the body size is level 1, 1.7 times level 2, else level 3.
- `demote` 1.2: a section header set in about the body size is text: typography classifies it as a paragraph
  again (layout models often call a bold run-in heading a section header).
- `split` 1.6, `max_headline_rows` 3: up to three leading rows of a text region this much taller than the rows after
  them and the body size are a headline the layout model merged into the text; they become a section header of
  their own.
- `page_number_min_conf` 0.75: a page-number region read with a lower mean character confidence (or empty) is an
  ornament or a blob, and is removed: typography classifies it `status` `removed` (with its confidence), and the
  rendering policy leaves it out.
- Drop capitals (a layout model's `drop-capital` class) are linked to the first line of the text region they
  belong to (a `part_of` link); the document writes the letter at that line's start, and the line's own text stays
  as read.
