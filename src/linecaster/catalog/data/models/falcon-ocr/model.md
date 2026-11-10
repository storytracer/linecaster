Falcon OCR is TII's early-fusion vision-language model for document OCR (plain text, LaTeX for formulas, HTML for
tables), a crop model by design: whole pages go through the vendor's pipeline service (a layout model, then one
request per crop with a category prompt, and the vendor's Markdown assembly) in the vendor image
`ghcr.io/tiiuae/falcon-ocr`. The image ships its own copy of the weights (`/models/Falcon-OCR`). This pin is the
revision those files are: in the vendor image the preset serves (`ghcr.io/tiiuae/falcon-ocr@sha256:2ec80252...`, the
preset's `serve.image`), every file of `/models/Falcon-OCR` has the git blob of this revision, `model.safetensors`
its sha256 (checked 2026-11-06; NOTES.md). The repository's later revisions (Falcon OCR v1.5, 2026-09-11) have other
weights. The card at this revision names no parameter count or language list (the newer card says 270M parameters).
License: Apache-2.0 (the card's front matter; the repository has no license file).
The upstream card is in `upstream/177110bf36f6fd492428215baf76d0618854bed3/README.md`.
