---
schema: linecaster.model/1
id: unlimited-ocr-2
version: Unlimited-OCR 2
source:
  kind: hf
  ref: baidu/Unlimited-OCR-2
pins:
- revision: 9cf077c4b206e0e2a31879df937b0b0bcba3661c
  pinned: 2026-11-03
  files:
    Unlimited-OCR-2.pdf: sha256:1eb5885f4ddfa4ec6fbff375092377f30b5d6a5e034ec4936213f125bf2f9444
    assets/HarryPotter.gif: sha256:572305c08be5a87c14b0c211d3ef28398a00818b341bfcfdb8152678bffa8ea5
    assets/Unlimited-OCR2.png: sha256:e231defdf9aebbf8d6cf6a6dc15ded22412629a2cbf196436e2d9b58973aa678
    assets/leaderboard.png: sha256:aca406f669dba1af337d7ac9b7be6dafad89b3afbf3570567c578b50dfeb9e8b
    assets/logo.png: sha256:e1c533934d3d5abaa1666c8ce858d4f2195b14471c7e3b8f3da772972359652d
    model-00001-of-00002.safetensors: sha256:4c40b740f209fd7682040d4ebf19409208acde5c401ccd2dde426d0f41542f18
    model-00002-of-00002.safetensors: sha256:9490b82fa47f89e5110eb5577f8ab1b6694c12121905dbc086ddb10207a4ba0c
    wheel/sglang-0.5.20.dev10+g8d62f5fb9c-py3-none-any.whl: sha256:a3f3e2c94e09de90b61b43d01475fd5d1aa818d16eec05204b8079c09c2ba70d
  card: upstream/9cf077c4b206e0e2a31879df937b0b0bcba3661c/README.md
  card_sha256: sha256:88c702fdb9988b3dc1808ff8e408c98934224cd77bf23de60046c8771cc3df0a
license: MIT
languages:
- mul
scripts: []
derived_from: []
---

Unlimited-OCR 2 ("Unlimited OCR Works 2") is Baidu's successor to Unlimited-OCR: Sparse Reference Sliding
Window Attention (SR-SWA) keeps decoding cost and memory nearly constant with document length, so whole
documents of hundreds of pages can be parsed in one pass. Pages go in as `<PAGE><image>` per page with the
`Multi page parsing.` prompt and the output has one `<PAGE>` per input page. It needs `trust_remote_code`
(custom code); upstream recommends a customised SGLang build for serving. The card says "multilingual" without
a list and names no base checkpoint. Licence: MIT (card front matter; no licence file was copied at pinning).
The upstream card is in `upstream/9cf077c4b206e0e2a31879df937b0b0bcba3661c/README.md`.
