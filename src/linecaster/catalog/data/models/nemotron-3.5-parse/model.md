Nemotron 3.5 Parse is NVIDIA's document image parser: one string per page with text, semantic layout classes,
bounding boxes and reading order (Markdown text by default; upstream helpers render Markdown with HTML tables,
or LaTeX/HTML/JSON/CSV tables). It combines a C-RADIOv4-SO400M vision encoder with a 10-layer mBART decoder,
about 0.631B parameters; the card names no base checkpoint. The card reports multilingual evaluation (10 Indic
languages; 163 language/script entries in 26 script groups on synthetic pages) but no list of supported
languages, so `languages` is `mul` and `scripts` is empty. License: OpenMDW License Agreement 1.1 for the
weights (copied as `upstream/62cb1e4ba153d113ff64aaf2be6e068c377cf53c/LICENSE`); the bundled tokenizer is MIT.
The upstream card is in `upstream/62cb1e4ba153d113ff64aaf2be6e068c377cf53c/README.md`.
