Tesseract's trained data from the tesseract-ocr project's `tessdata_fast` repository: integer LSTM models, faster and slightly less accurate than best, for Tesseract 4
and later with the LSTM engine. The repository has no tags; the pin is a commit, and the two files linecaster's
presets use are hashed: `eng.traineddata` (English) and `script/Latin.traineddata` (every language written in the
Latin script). `languages` and `scripts` describe these two files only (the repository has many more; the
Latin script model covers many Latin-script languages, of which the README names none). Licence: Apache-2.0, as
the README states and its `LICENSE` file (copied next to it) says.

Files are fetched from `raw.githubusercontent.com` at the pinned commit into `~/.cache/linecaster/tessdata` and
checked against these hashes whenever they are used.
