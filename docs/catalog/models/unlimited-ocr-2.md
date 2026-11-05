# unlimited-ocr-2

*Model · Unlimited-OCR 2 · MIT*

Unlimited-OCR 2 ("Unlimited OCR Works 2") is Baidu's successor to Unlimited-OCR: Sparse Reference Sliding
Window Attention (SR-SWA) keeps decoding cost and memory nearly constant with document length, so whole
documents of hundreds of pages can be parsed in one pass. Pages go in as `<PAGE><image>` per page with the
`Multi page parsing.` prompt and the output has one `<PAGE>` per input page. It needs `trust_remote_code`
(custom code); upstream recommends a customized SGLang build for serving. The card says "multilingual" without
a list and names no base checkpoint. License: MIT (card front matter; no license file was copied at pinning).
The upstream card is in `upstream/9cf077c4b206e0e2a31879df937b0b0bcba3661c/README.md`.

|  |  |
|---|---|
| Source | [baidu/Unlimited-OCR-2](https://huggingface.co/baidu/Unlimited-OCR-2) |
| License | MIT |
| Languages | mul |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `9cf077c4b206e0e2a31879df937b0b0bcba3661c` | 2026-11-03 |  | 8 | [README.md](../../../src/linecaster/catalog/data/models/unlimited-ocr-2/upstream/9cf077c4b206e0e2a31879df937b0b0bcba3661c/README.md) |

## Presets

- [`unlimited-ocr-2`](../presets/recognition/unlimited-ocr-2.md)
