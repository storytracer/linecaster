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
- layout_detection
---

# PP-DocLayout_plus-L

## Introduction

A higher-precision layout area localization model trained on a self-built dataset containing Chinese and English papers, PPT, multi-layout magazines, contracts, books, exams, ancient books and research reports using RT-DETR-L. The layout detection model includes 20 common categories: document title, paragraph title, text, page number, abstract, table, references, footnotes, header, footer, algorithm, formula, formula number, image, table, seal, figure_table title, chart, and sidebar text and lists of references. The key metrics are as follow:

| Model| mAP(0.5) (%) |
|  --- | --- |
|PP-DocLayout_plus-L |  83.2 |

**Note**: the evaluation set of the above precision indicators is the self built version sub area detection data set, including Chinese and English papers, magazines, newspapers, research reports PPT、 1000 document type pictures such as test papers and textbooks.

## Model Usage

### Install Dependencies

```shell
pip install -U paddleocr
pip install -U onnxruntime-gpu
```

### CLI Usage

```shell
paddleocr layout_detection -i ./demo.jpg --model_name PP-DocLayout_plus-L --engine onnxruntime
```

### Python API Usage

```python
from paddleocr import LayoutDetection

model = LayoutDetection(
    model_name="PP-DocLayout_plus-L",
    engine="onnxruntime",
)
output = model.predict("./demo.jpg", batch_size=1)
for res in output:
    res.print()
    res.save_to_img(save_path="./output/")
    res.save_to_json(save_path="./output/res.json")
```