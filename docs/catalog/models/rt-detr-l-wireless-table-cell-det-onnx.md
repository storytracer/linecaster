# rt-detr-l-wireless-table-cell-det-onnx

*Model · RT-DETR-L_wireless_table_cell_det · Apache-2.0*

PaddleOCR's RT-DETR-L_wireless_table_cell_det: the cell detector for wireless (unruled) tables in PaddleX's table pipeline. This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/RT-DETR-L_wireless_table_cell_det_onnx`, an export of `PaddlePaddle/RT-DETR-L_wireless_table_cell_det`; the card does not say from which revision).
Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).

|  |  |
|---|---|
| Source | [PaddlePaddle/RT-DETR-L_wireless_table_cell_det_onnx](https://huggingface.co/PaddlePaddle/RT-DETR-L_wireless_table_cell_det_onnx) |
| Licence | Apache-2.0 |
| Languages | eng, zho |
| Derived from | converted of PaddlePaddle/RT-DETR-L_wireless_table_cell_det |

## Pins

Each with the upstream card as published at that revision, verbatim.

| Revision | Pinned | Tag | Files | Card |
|---|---|---|---|---|
| `94c021be206064f0136ef1383fbd4b68b168fa61` | 2026-11-03 |  | 1 | [README.md](../../../src/linecaster/catalog/data/models/rt-detr-l-wireless-table-cell-det-onnx/upstream/94c021be206064f0136ef1383fbd4b68b168fa61/README.md) |

## Presets

- [`slanet-plus`](../presets/tables/slanet-plus.md)
