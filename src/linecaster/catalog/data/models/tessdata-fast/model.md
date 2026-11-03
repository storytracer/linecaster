---
schema: linecaster.model/1
id: tessdata-fast
version: tessdata_fast
source:
  kind: git
  ref: https://github.com/tesseract-ocr/tessdata_fast
pins:
- revision: 87416418657359cb625c412a48b6e1d6d41c29bd
  pinned: 2026-11-03
  files:
    eng.traineddata: sha256:7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2
    script/Latin.traineddata: sha256:6dbdaf8ecc6c40f025c2648bf3b3f3fbffe073e1fd2df2047fde2e2b2f020d53
  card: upstream/87416418657359cb625c412a48b6e1d6d41c29bd/README.md
  card_sha256: sha256:22fee9835bff02fb7013aa9786a2144ae3d4c219083089375985a62808e7215e
  license_file: upstream/87416418657359cb625c412a48b6e1d6d41c29bd/LICENSE
license: Apache-2.0
languages:
- eng
- mul
scripts:
- Latn
derived_from: []
---

Tesseract's trained data from the tesseract-ocr project's `tessdata_fast` repository: integer LSTM models, faster and slightly less accurate than best, for Tesseract 4
and later with the LSTM engine. The repository has no tags; the pin is a commit, and the two files linecaster's
presets use are hashed: `eng.traineddata` (English) and `script/Latin.traineddata` (every language written in the
Latin script). `languages` and `scripts` describe these two files only (the repository has many more; the
Latin script model covers many Latin-script languages, of which the README names none). Licence: Apache-2.0, as
the README states and its `LICENSE` file (copied next to it) says.

Files are fetched from `raw.githubusercontent.com` at the pinned commit into `~/.cache/linecaster/tessdata` and
checked against these hashes whenever they are used.
