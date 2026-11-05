PaddleOCR's RT-DETR-L_wireless_table_cell_det: the cell detector for wireless (unruled) tables in PaddleX's table pipeline. This is the ONNX package PaddleX downloads for its ONNX Runtime engine
(`PaddlePaddle/RT-DETR-L_wireless_table_cell_det_onnx`, an export of `PaddlePaddle/RT-DETR-L_wireless_table_cell_det`; the card does not say from which revision).
Licence and languages are the card's.

PaddleX itself always downloads the repository's current `main`; linecaster pins the commit that was `main` on
2026-11-03 (for every model PaddleX had already downloaded on spark, among them those of squiddleocr's goldens,
the commit its cached files came from) and loads that snapshot from the Hugging Face cache through
`create_predictor(model_dir=...)`. On three pages (text, table, formulas) it gave the same output as PaddleX's
own download (2026-11-03).
