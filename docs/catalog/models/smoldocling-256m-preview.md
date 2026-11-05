# smoldocling-256m-preview

*Model · SmolDocling-256M-preview · CDLA-Permissive-2.0*

SmolDocling-256M-preview is the Docling team's (IBM Research) ultra-compact document conversion VLM (arXiv
2503.11576): it writes a page as DocTags (layout, boxes, tables, code, formulas, charts, captions), which
docling-core turns into a DoclingDocument and from there into Markdown or HTML. It is fine-tuned from
SmolVLM-256M-Instruct; English only. Upstream has superseded it with granite-docling-258M. The repository has
moved: linecaster pins `ds4sd/SmolDocling-256M-preview`, which now redirects to
`docling-project/SmolDocling-256M-preview`. License: the card front matter says CDLA-Permissive-2.0, while its
model summary says Apache 2.0; the front matter value is recorded.
The upstream card is in `upstream/ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8/README.md`.

|  |  |
|---|---|
| Source | [ds4sd/SmolDocling-256M-preview](https://huggingface.co/ds4sd/SmolDocling-256M-preview) |
| License | CDLA-Permissive-2.0 |
| Languages | eng |
| Scripts | Latn |
| Parameters | 256M |
| Derived from | finetuned of HuggingFaceTB/SmolVLM-256M-Instruct |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8` | 2026-11-03 |  | 27 | [README.md](../../../src/linecaster/catalog/data/models/smoldocling-256m-preview/upstream/ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8/README.md) |

## Presets

- [`smoldocling-256m-preview`](../presets/recognition/smoldocling-256m-preview.md)
