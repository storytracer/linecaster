The item stage's default combination: each item's pages recomposed as one item (`unicode-recomposition`: paragraphs
continued across page breaks, the item's own words as the lexicon), normalized for reading (`latin-historic`: long
s, ligatures, r rotunda and superscript e folded) and composed into the item's document (`docling-composition`). It
writes the text variants `verbatim_txt`, `readable_txt` and `readable_md` and the item document in md, txt and json.

- The readable texts come from the recomposition since phase 3 of the refactoring; before, a simpler flow joined each
  region's lines (NOTES.md has the comparison on the BHL ground truth's whole items).
- For historic print in Latin script; other scripts are recomposed by the same Unicode rules, and the normalization
  leaves their characters as they are.
