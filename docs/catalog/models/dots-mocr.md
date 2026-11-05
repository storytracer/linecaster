# dots-mocr

*Model · dots.mocr · MIT*

dots.mocr is rednote-hilab's multilingual document parser, the successor to dots.ocr (arXiv 2603.13032): one
3B vision-language model that returns the page layout as a single JSON object (box, category and text per
element; formulas as LaTeX, tables as HTML, other text as Markdown), and can also parse charts and other
graphics into SVG code (a separate dots.mocr-svg variant is tuned for that). It needs `trust_remote_code`
(custom code); vLLM supports it natively. The repository has moved: linecaster pins `rednote-hilab/dots.mocr`,
which now redirects to `dots-studio/dots.mocr`. The card names no base model. Licence: MIT.
The upstream card is in `upstream/e539fbb52280393adc081b289ec597430a0f9031/README.md`.

|  |  |
|---|---|
| Source | [rednote-hilab/dots.mocr](https://huggingface.co/rednote-hilab/dots.mocr) |
| Licence | MIT |
| Languages | eng, zho, mul |
| Scripts | Latn, Hani |
| Parameters | 3B |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `e539fbb52280393adc081b289ec597430a0f9031` | 2026-11-03 |  | 2 | [README.md](../../../src/linecaster/catalog/data/models/dots-mocr/upstream/e539fbb52280393adc081b289ec597430a0f9031/README.md) |

## Presets

- [`dots-mocr`](../presets/recognition/dots-mocr.md)
