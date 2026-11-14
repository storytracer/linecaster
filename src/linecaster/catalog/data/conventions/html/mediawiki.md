## Source

MediaWiki's own markup and that of its extensions as every wiki has it, independent of any wiki's templates:
Cite (`<ref>`, `<references>`), Scribunto (Lua modules), ProofreadPage (`Page:` pages with their header, body and
footer, Index pages), TemplateStyles, Math, Poem. Written against MediaWiki 1.48 and the MediaWiki importer
(`import.mediawiki.v1`), which expands a page's wikitext with wikitextprocessor and writes it as HTML.

## How the markup works

Most of MediaWiki's meaning reaches the importer as standard HTML, which the HTML importer reads without
conventions: ProofreadPage's header and footer become the page's `doc-pageheader` and `doc-pagefooter`, Cite's
notes `doc-footnote` elements where their marks stand, Math's formulas MathML `math` elements with their TeX in
`alttext`, Poem's lines line breaks and its stanzas paragraphs, TemplateStyles' style sheets `<style>` elements. What
remains is what only MediaWiki's classes say: the software's error messages (`.error`), and a note that continues
one from an earlier page (`mw-ref-follow`, the importer's class for `<ref follow=...>`).

## Not in the rules

- A reuse of a named note (`<ref name=x/>`) prints nothing where it stands; the importer leaves it out.
- `<references/>` prints nothing: the notes are read where their marks are, as on the printed page.
- Templates whose output carries no class of its own cannot be told apart in the HTML; a wiki's conventions say
  what its templates' classes mean.

## Open questions

- Note groups (`<ref group=...>`) are kept as an attribute (`data-group`); whether a wiki's group is part of the page
  (a group of printed notes) or an editors' apparatus is the wiki's convention.
