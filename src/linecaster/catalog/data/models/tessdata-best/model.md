Tesseract's trained data from the tesseract-ocr project's `tessdata_best` repository: the most accurate LSTM models (float), for Tesseract 4
and later with the LSTM engine. The repository has no tags; the pin is a commit, and the files linecaster's presets
use are hashed: `eng.traineddata` (English) and the script models `script/Latin`, `Fraktur`, `Greek`, `Cyrillic`,
`Arabic`, `Hebrew`, `Devanagari`, `Thai`, `Hangul`, `HanT_vert` (traditional Chinese set vertically) and
`Japanese_vert` (Japanese set vertically), each covering the languages written in its script. `languages` and
`scripts` describe these files only (the repository has many more; the README names no languages of the script
models). License: Apache-2.0, as
the README states and its `LICENSE` file (copied next to it) says.

Files are fetched from `raw.githubusercontent.com` at the pinned commit into `~/.cache/linecaster/tessdata` and
checked against these hashes whenever they are used.
