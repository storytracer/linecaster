---
license: apache-2.0
library_name: PaddleOCR
language:
- en
- zh
pipeline_tag: image-to-text
tags:
- OCR
- PaddlePaddle
- PaddleOCR
- table_cells_detection
---

# RT-DETR-L_wired_table_cell_det

## Introduction

The Table Cell Detection Module is a key component of the table recognition task, responsible for locating and marking each cell region in table images. The performance of this module directly affects the accuracy and efficiency of the entire table recognition process. The Table Cell Detection Module typically outputs bounding boxes for each cell region, which are then passed as input to the table recognition pipeline for further processing.


<table>
<tr>
<th>Model</th>
<th>Top1 Acc(%)</th>
<th>GPU Inference Time (ms)<br/>[Regular Mode / High-Performance Mode]</th>
<th>CPU Inference Time (ms)<br/>[Regular Mode / High-Performance Mode]</th>
<th>Model Storage Size (M)</th>
</tr>
<tr>
<td>RT-DETR-L_wired_table_cell_det</td>
<td>82.7</td>
<td>35.00 / 10.45</td>
<td>495.51 / 495.51</td>
<td>124M</td>
</tr>
</table>

**Note**: The accuracy of RT-DETR-L_wired_table_cell_det comes from the results of joint testing with RT-DETR-L_wireless_table_cell_det.

## Model Usage

### Install Dependencies

```shell
pip install -U paddleocr
pip install -U onnxruntime-gpu
```

### CLI Usage

```shell
paddleocr table_cells_detection -i ./demo.jpg --model_name RT-DETR-L_wired_table_cell_det --engine onnxruntime
```

### Python API Usage

```python
from paddleocr import TableCellsDetection

model = TableCellsDetection(
    model_name="RT-DETR-L_wired_table_cell_det",
    engine="onnxruntime",
)
output = model.predict("./demo.jpg", batch_size=1)
for res in output:
    res.print()
    res.save_to_img(save_path="./output/")
    res.save_to_json(save_path="./output/res.json")
```