Falcon OCR is TII's 270M-parameter early-fusion vision-language model for document OCR (plain text, LaTeX for
formulas, HTML for tables), a crop model by design: whole pages go through the vendor's pipeline service (a layout
model of about 30M parameters, then one request per crop with a category prompt, and the vendor's Markdown assembly)
in the vendor image `ghcr.io/tiiuae/falcon-ocr`. The image ships its own copy of the weights: what runs is fixed by
the image digest in the preset's `serve.image`, and this pin (the repository's head on the day it was pinned) holds
the card. Whether the image's weights are this pin's files is not checked. The card names no language list.
License: Apache-2.0 (the card's front matter; the repository has no license file).
The upstream card is in `upstream/0bc28f89c90fbe8bdb063097fab144d4ce4c19b5/README.md`.
