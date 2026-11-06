---
license: apache-2.0
pipeline_tag: image-to-text
library_name: transformers
tags:
- falcon
- ocr
- vision-language
- document-understanding
---

# Falcon OCR

Dense early-fusion vision-language model for **document OCR**. Given a document image, it extracts text, tables, formulas, and other elements as plain text.

## Installation

```bash
pip install transformers torch einops
```

Requires **PyTorch 2.5+** (FlexAttention).

## Quick Start

```python
import torch
from transformers import AutoModelForCausalLM
from PIL import Image

model = AutoModelForCausalLM.from_pretrained(
    "tiiuae/Falcon-OCR",
    trust_remote_code=True,
    dtype=torch.bfloat16,
    device_map="cuda",
)

image = Image.open("document.png")
texts = model.generate(image)
print(texts[0])
```

> The first `generate()` call is slower due to `torch.compile` building optimized kernels. Subsequent calls are much faster.

## Categories

By default, category is `"plain"` (general text extraction). You can specify a category to use a task-specific prompt:

```python
texts = model.generate(image, category="table")
texts = model.generate(image, category="formula")
```
**Returns:** `list[str]` — one extracted text string per image.

Available categories: `plain`, `text`, `table`, `formula`, `caption`, `footnote`, `list-item`, `page-footer`, `page-header`, `section-header`, `title`.


## Layout OCR

For most documents, `generate()` works well out of the box — the model handles mixed content (text, tables, formulas) in a single pass. For very dense or complex documents with many heterogeneous regions, you can use the two-stage **layout detection + per-region OCR** pipeline:

```python
results = model.generate_with_layout(image)

for det in results[0]:
    print(f"[{det['category']}] {det['text'][:100]}...")
```

This runs [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_safetensors) to detect regions (text blocks, tables, formulas, etc.), then OCRs each crop with the appropriate category-specific prompt. Nested boxes (e.g. inline formulas inside text) are automatically filtered.

```python
# Batch of pages
results = model.generate_with_layout(
    [Image.open("page1.png"), Image.open("page2.png")],
    ocr_batch_size=32,
)

# results[0] = list of dicts for page 1
# results[1] = list of dicts for page 2
for det in results[0]:
    print(det["category"], det["bbox"], det["score"])
    print(det["text"])
```

> The layout model is loaded lazily on the first `generate_with_layout()` call (~100 MB). It runs on the same GPU as the OCR model.


**Returns:** `list[list[dict]]` — per image, a list of detections in reading order:

```python
{
    "category": "text",       # layout category
    "bbox": [x1, y1, x2, y2], # in original image pixels
    "score": 0.93,            # detection confidence
    "text": "..."             # extracted text
}
```

## Capabilities
### Handwriting
<img src="https://cdn-uploads.huggingface.co/production/uploads/62fe441427c98b09b503a4e3/zX9GbTqZ2Jbazey4AOBGH.png" width="600" />

### Real-world images
<img src="https://cdn-uploads.huggingface.co/production/uploads/62fe441427c98b09b503a4e3/xvyXcFXMfNkCM-3r0_-fu.png" width="600" />

### Tables

<img src="https://cdn-uploads.huggingface.co/production/uploads/62fe441427c98b09b503a4e3/3VqNXV6awVZynM0X2QE9U.png" width="600" />

### Complex Layout

<img src="https://cdn-uploads.huggingface.co/production/uploads/62fe441427c98b09b503a4e3/iGCYI2y1eaCj1wMHrmNds.png" width="600" />

<!-- ![image](https://cdn-uploads.huggingface.co/production/uploads/62fe441427c98b09b503a4e3/iGCYI2y1eaCj1wMHrmNds.png) -->

## Citation


