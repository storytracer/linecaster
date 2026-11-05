# chat.v1

*Engine · page · package `linecaster`*

Base class of a chat-VLM adapter. A subclass sets `adapter` (its registry name) and implements
`request`; `parse` has a text-only default. Every value comes from the preset:

* `model` / `revision`: the Hugging Face id and pinned commit; `served_name`: the name the server
  hosts it under (`options.served_name`, default the Hub id);
* `sampling`, `prompt`, `page_longest` (the page size the model expects, longest side in px; also
  the scale `RegionRecognizer` cuts regions at), `region_pad` and the adapter's own `settings`;
* `server` (`vllm` or `sglang`), `server_version`, `job_image`, `serve_args` (the server's
  flags after the model, not port/host) and `server_env` from the `serve` block;
* `revision_flag` (pass `--revision`; `False` for a server that must load the default branch, which
  the serve block then checks file by file against the pin, `pin_ignore` aside) and
  `server_packages` (installed into the server's Python first) from the serve block or, until the
  serve schema has them, `options`.

|  |  |
|---|---|
| Class | `linecaster.adapters:ChatAdapter` |
| Source | [__init__.py](../../../src/linecaster/adapters/__init__.py) |

## Adapters

Each preset names one in `options.adapter`: the request and the parsing of the answer.

| Adapter | Source |
|---|---|
| `chandra-ocr` | [chandra_ocr2.py](../../../src/linecaster/adapters/chandra_ocr2.py) |
| `deepseek-ocr` | [deepseek_ocr.py](../../../src/linecaster/adapters/deepseek_ocr.py) |
| `dots` | [dots.py](../../../src/linecaster/adapters/dots.py) |
| `glm-ocr` | [glm_ocr.py](../../../src/linecaster/adapters/glm_ocr.py) |
| `lighton-ocr-2` | [lighton_ocr2.py](../../../src/linecaster/adapters/lighton_ocr2.py) |
| `lighton-ocr-3` | [lighton_ocr3.py](../../../src/linecaster/adapters/lighton_ocr3.py) |
| `minicpm-ocr` | [minicpm_ocr.py](../../../src/linecaster/adapters/minicpm_ocr.py) |
| `nemotron-parse` | [nemotron_parse35.py](../../../src/linecaster/adapters/nemotron_parse35.py) |
| `olmocr` | [olmocr2.py](../../../src/linecaster/adapters/olmocr2.py) |
| `ovis-ocr` | [ovis_ocr.py](../../../src/linecaster/adapters/ovis_ocr.py) |
| `paddleocr-vl` | [paddleocr_vl.py](../../../src/linecaster/adapters/paddleocr_vl.py) |
| `qianfan-ocr` | [qianfan_ocr.py](../../../src/linecaster/adapters/qianfan_ocr.py) |
| `qwen3.5` | [qwen35.py](../../../src/linecaster/adapters/qwen35.py) |
| `smoldocling` | [smoldocling.py](../../../src/linecaster/adapters/smoldocling.py) |
| `unlimited-ocr` | [unlimited_ocr.py](../../../src/linecaster/adapters/unlimited_ocr.py) |
| `unlimited-ocr-2` | [unlimited_ocr.py](../../../src/linecaster/adapters/unlimited_ocr.py) |

## Presets

- [`chandra-ocr-2`](../presets/page/chandra-ocr-2.md)
- [`deepseek-ocr`](../presets/page/deepseek-ocr.md)
- [`deepseek-ocr-2`](../presets/page/deepseek-ocr-2.md)
- [`dots-mocr`](../presets/page/dots-mocr.md)
- [`dots-ocr`](../presets/page/dots-ocr.md)
- [`glm-ocr`](../presets/page/glm-ocr.md)
- [`lightonocr-2-1b`](../presets/page/lightonocr-2-1b.md)
- [`lightonocr-2-1b-regions`](../presets/recognition/lightonocr-2-1b-regions.md)
- [`lightonocr-3-0.8b`](../presets/page/lightonocr-3-0.8b.md)
- [`lightonocr-3-4b`](../presets/page/lightonocr-3-4b.md)
- [`minicpm-ocr-1.0`](../presets/recognition/minicpm-ocr-1.0.md)
- [`nemotron-3.5-parse`](../presets/page/nemotron-3.5-parse.md)
- [`olmocr-2-7b-1025-fp8`](../presets/page/olmocr-2-7b-1025-fp8.md)
- [`ovisocr2`](../presets/page/ovisocr2.md)
- [`ovisocr3`](../presets/page/ovisocr3.md)
- [`paddleocr-vl-1.6`](../presets/page/paddleocr-vl-1.6.md)
- [`qianfan-ocr`](../presets/page/qianfan-ocr.md)
- [`qwen3.5-9b`](../presets/page/qwen3.5-9b.md)
- [`smoldocling-256m-preview`](../presets/page/smoldocling-256m-preview.md)
- [`unlimited-ocr`](../presets/page/unlimited-ocr.md)
- [`unlimited-ocr-2`](../presets/page/unlimited-ocr-2.md)
