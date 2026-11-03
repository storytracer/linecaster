# tessdata-best

*Model · tessdata_best · Apache-2.0*

Tesseract's trained data from the tesseract-ocr project's `tessdata_best` repository: the most accurate LSTM models (float), for Tesseract 4
and later with the LSTM engine. The repository has no tags; the pin is a commit, and the two files linecaster's
presets use are hashed: `eng.traineddata` (English) and `script/Latin.traineddata` (every language written in the
Latin script). `languages` and `scripts` describe these two files only (the repository has many more; the
Latin script model covers many Latin-script languages, of which the README names none). Licence: Apache-2.0, as
the README states and its `LICENSE` file (copied next to it) says.

Files are fetched from `raw.githubusercontent.com` at the pinned commit into `~/.cache/linecaster/tessdata` and
checked against these hashes whenever they are used.

|  |  |
|---|---|
| Source | [https://github.com/tesseract-ocr/tessdata_best](https://github.com/tesseract-ocr/tessdata_best) |
| Licence | Apache-2.0 |
| Languages | eng, mul |
| Scripts | Latn |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `e12c65a915945e4c28e237a9b52bc4a8f39a0cec` | 2026-11-03 |  | 2 | [README.md](../../../src/linecaster/catalog/data/models/tessdata-best/upstream/e12c65a915945e4c28e237a9b52bc4a8f39a0cec/README.md) |

## Presets

- [`tesseract-best-eng`](../presets/recognition/tesseract-best-eng.md)
- [`tesseract-best-latin`](../presets/recognition/tesseract-best-latin.md)
