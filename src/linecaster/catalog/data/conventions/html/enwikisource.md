## Source

English Wikisource (en.wikisource.org), its `Page:` pages as their wikitext is read by the MediaWiki importer:
expanded with the wiki's own templates, Lua modules and style sheets from the dump of 2026-11-01, built into HTML.
The rules match the classes and attributes the templates write; they extend `mediawiki`, which holds what
MediaWiki and its extensions write on every wiki.

## How the markup works

English Wikisource's editors transcribe a scanned page into its `Page:` page: the running head and anything
printed above the text in the page's header, the text in its body, a footer below. They mark what the page prints
with templates whose output is HTML with classes of their own (`wst-*`, `ws-*`) and TemplateStyles style sheets:
the running head's left, centre and right (`{{RunningHeader}}`, `{{rh}}`), centred and indented blocks, poems
(`{{ppoem}}`), sidenotes, ditto marks, dot leaders in tables of contents, figures (`{{FreedImg}}`), corrections of
printing errors (`{{SIC}}`) and notes of the editors (`{{tooltip}}`, `{{Errata}}`). Most of it is read by HTML's own
semantics: blocks and inline elements, `visibility: hidden` (`{{dhr}}`, `{{gap}}`), `text-transform` in the
style sheets (`{{uc}}`, an Index's styles), ARIA headings, `lang`. The rules say the rest: what a class means where
HTML does not.

A page's last paragraph runs on onto the next page unless the page ends it: `{{nop}}` marks the end of a paragraph
at a page's end.

- **Stanzas across a page break** (editions 2 and 3): `{{ppoem}}` writes a complete poem on each `Page:` page, and
  `start=follow` / `end=follow` join a stanza only in the main namespace. The reader records each top-level
  template call on the first element it writes (`data-mw-template`, `data-mw-param-<name>`), so the rules match
  the call: a page's first stanza `continues` (on the poem's element), its last `runs_on` (on its stanzas: one
  element takes one decision, and a call can have both). Each page reads as it is; an item joins them.
- **Words divided across a page break** (edition 4): `{{hws}}` and `{{hwe}}` (`{{hyphenated word start}}`,
  `{{hyphenated word end}}`) write each half as printed, in a span whose `title` is the whole word; the main namespace
  prints the whole word where `{{hwe}}` stands and nothing for `{{hws}}`. Each half is read as printed with a
  `joined` edit giving the whole word; an item's pages read together (`link_pages`) pair the halves and write the
  whole word, including a compound's own hyphen (`inter-crossing`), where the wiki does. The reader marks a call
  inside a line too when a rule names its template, so the rule matches the span the call writes.

## Not in the rules

- Templates whose output has no class of its own and that no rule names cannot be matched in the HTML: `{{ua}}` (an
  editor's note, its text followed by "(Wikisource contributor note)"). Its text is read as printed text.
- A word divided across two pages is joined only where an item's pages are read together, not on one page.
- What `{{FreedImg}}` and a file link show is a picture region with the file's name; the importer has no image.

## Open questions

- `{{ua}}`: a rule naming the template (`[data-mw-template=Ua]`) would match its output as `{{hws}}`'s is.
- Dot leaders (`ws-noexport`) are removed whole; a list of illustrations that sets credits inside the leader element
  loses them.
