---
pipeline_tag: image-to-text
library_name: transformers
tags:
- falcon
- ocr
- vision-language
- document-understanding
- v1.5
license: apache-2.0
---


<div style="width: 480px; text-align: left;">
  <img src="https://cdn-uploads.huggingface.co/production/uploads/663c9939c1b4f7297c4ae6f6/YIuxzgDiV5T2ZuSB4bam9.png" alt="Falcon OCR Logo" style="max-width: 100%; height: auto;">
</div>

# Falcon OCR

Falcon OCR is a 270M parameter early-fusion vision-language model for document OCR. Given an image, it can produce plain text, LaTeX for formulas, or HTML for tables.

Most OCR VLM systems are built as a pipeline with a vision encoder feeding a separate text decoder, plus additional task-specific glue. Falcon OCR takes a different approach: a single Transformer processes image patches and text tokens in a shared parameter space from the first layer, using a hybrid attention mask where image tokens attend bidirectionally and text tokens decode causally conditioned on the image.

We built it this way for two practical reasons. First, it keeps the interface simple: one backbone, one decoding path, and task switching through prompts rather than a growing set of modules. Second, a 270M model has a lower latency and cost footprint than 0.9B-class OCR VLMs, and in our vLLM-based serving setup this translates into higher throughput, often 2–3× faster depending on sequence lengths and batch configuration. To our knowledge, this is one of the first attempts to apply this early-fusion single-stack recipe directly to competitive document OCR at this scale.

### Links

- Code and inference engine: [https://github.com/tiiuae/Falcon-Perception](https://github.com/tiiuae/Falcon-Perception)
- Tech report: [https://arxiv.org/pdf/2603.27365](https://arxiv.org/pdf/2603.27365)
- Perception model: `tiiuae/falcon-perception`
- vLLM/Docker: [https://ghcr.io/tiiuae/falcon-ocr:latest](https://ghcr.io/tiiuae/falcon-ocr:latest)

## Model updates

| Date | Update |
|------|--------|
| 2026-09-11 | **1.5** — Updated `model.safetensors`. Improved real-world document handling, complex tables, handwriting, and degraded/historical scans; better end-to-end OCR and reduced hallucinations. |

### Broader document coverage

We rebuilt the finetuning mix to balance the old strengths with new sources:

- **Historical and scanned documets**
- **Handwriting and real-world captures** — notes, forms, photos with text in scene
- **Everyday documents** —receipts, magazines, book scans, exam papers
- **Hard tables** — multi-table PDFs, synthetic complex and real-world tables
- **Internal data**

### RL

We further post-trained Falcon-OCR-1.5 with GRPO. This allows, for instance, to mitigate hallucinations (plausible text that isn't on the page) or runaway loops (the model keeps repeating a phrase or a table row) as well as table and formulas correctness and formatting.

#### Element-wise reward attribution

For the rewards, we use first element-wise attribution: we match blocks to corresponding GT using OmniDocBench style matching (text, formulas table), all the tokens in the match get assigned a reward and an advantage measuring its fidelity with respect to the ground-truth.  This is measured by its native metric:

| Element | Reward signal |
| --- | --- |
| text | character edit distance |
| formula | latex validity × (1 − edit distance) |
| table | TEDS (tree-edit structural similarity) |


#### Structural Rewards

On top of the per-element scores, a small set of structural gates put the entire rollout's reward to zero for the degenerate behaviors we want to avoid:

- **Repetition / loops**: caught two ways: a compression check for catastrophic collapse, plus a word-n-gram detector.
- **Omission**: outputs that silently drop ground-truth blocks.
- **Over-generation**: outputs far longer than the page.

## Quickstart

### Installation

```bash
pip install "torch>=2.5" transformers pillow einops
```

Falcon OCR requires PyTorch 2.5 or newer for FlexAttention. The first call may be slower as `torch.compile` builds optimized kernels.

### Single-Image OCR

```python
import torch
from PIL import Image
from transformers import AutoModelForCausalLM
model = AutoModelForCausalLM.from_pretrained(
    "tiiuae/Falcon-OCR",
    trust_remote_code=True,
    torch_dtype=torch.bfloat16,
    device_map="auto",
)
image = Image.open("document.png")
texts = model.generate(image)  # default category is "plain"
print(texts[0])
```

### Choose an output format with `category`

```python
texts = model.generate(image, category="text")     # plain text
texts = model.generate(image, category="formula")  # LaTeX
texts = model.generate(image, category="table")    # HTML table
```

## API

### `model.generate(images, category="plain", **kwargs)`
- **Inputs**:
  - `images`: a `PIL.Image.Image` or a list of images
  - `category`: one of `plain`, `text`, `table`, `formula`, `caption`, `footnote`, `list-item`, `page-footer`, `page-header`, `section-header`, `title`
- **Returns**: `list[str]`, one extracted string per image

## Layout OCR (Two-Stage Pipeline)
**We recommend end-to-end OCR (`model.generate`) for most documents** — send the full page directly to the model. Use layout + OCR only for very dense pages (e.g. dense newspapers). The optional two-stage pipeline:
1. A layout detector finds regions on the page.
2. Falcon OCR runs independently on each crop with a category-specific prompt.
We use [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_safetensors) as the layout detector.
```python
results = model.generate_with_layout(image)
for det in results[0]:
    print(f"[{det['category']}] {det['text'][:100]}...")
```
Batch mode:
```python
results = model.generate_with_layout(
    [Image.open("page1.png"), Image.open("page2.png")],
    ocr_batch_size=32,
)
```
The layout model is loaded lazily on the first `generate_with_layout()` call and runs on the same GPU as the OCR model.
**Returns**: `list[list[dict]]`, one list per image, in reading order:
```python
{
    "category": "text",       # layout category
    "bbox": [x1, y1, x2, y2], # in original image pixels
    "score": 0.93,            # detection confidence
    "text": "..."             # extracted text
}
```

## When to Use What

| Mode | Best for | How |
|------|----------|-----|
| **End-to-end OCR** (recommended) | Photos, receipts, slides, handwriting, scans, most documents | `model.generate(image)` |
| **Layout + OCR** | Very dense multi-column pages (newspapers, tightly packed layouts) | `model.generate_with_layout(image)` |



## Benchmark Results
<details name="benchmarks" open>
<summary><b>olmOCR Benchmark</b></summary>

Category-wise accuracy (%) on olmOCR splits. We omit the official Header/Footer category — it penalizes faithfully reproducing visible page headers and footers.

<table>
<tr><th>Model</th><th>Average</th><th>ArXiv Math</th><th>Base</th><th>TinyTxt</th><th>MultCol</th><th>OldScan</th><th>OldMath</th><th>Tables</th></tr>
<tr><td>dots-mocr</td><td><b>84.0</b></td><td>85.9</td><td>99.7</td><td>93.9</td><td>86.5</td><td><b>48.5</b></td><td>82.3</td><td><b>91.4</b></td></tr>
<tr><td>chandra-ocr-2</td><td>83.8</td><td>86.5</td><td>99.9</td><td>93.4</td><td>83.9</td><td>49.0</td><td>83.4</td><td>90.2</td></tr>
<tr><td>mineru2.5-pro</td><td>81.5</td><td>87.1</td><td>99.5</td><td>93.7</td><td>84.4</td><td>36.1</td><td>83.4</td><td>86.0</td></tr>
<tr><td>ovis-ocr-2</td><td>81.2</td><td><b>89.3</b></td><td>98.0</td><td>92.8</td><td><b>87.4</b></td><td>33.1</td><td>80.3</td><td>87.5</td></tr>
<tr><td>paddleocr-vl-1.6</td><td>78.7</td><td>87.8</td><td>98.4</td><td>91.6</td><td>84.1</td><td>39.0</td><td>68.8</td><td>81.3</td></tr>
<tr><td>unlimited-ocr</td><td>78.5</td><td>86.1</td><td>99.5</td><td>91.2</td><td>85.8</td><td>30.6</td><td>72.3</td><td>83.7</td></tr>
<tr><td>hunyuan-ocr-1.5</td><td>78.0</td><td>86.9</td><td>99.8</td><td>89.6</td><td>80.6</td><td>35.2</td><td>75.1</td><td>78.7</td></tr>
<tr><td>glm-ocr</td><td>76.1</td><td>80.3</td><td>98.9</td><td>91.4</td><td>78.6</td><td>41.6</td><td>66.8</td><td>74.8</td></tr>
<tr><td>deepseek-ocr-2</td><td>73.3</td><td>78.8</td><td>97.4</td><td>81.7</td><td>82.2</td><td>31.2</td><td>65.7</td><td>75.8</td></tr>
<tr style="background:#a358e5; color:white"><td><b>Falcon OCR 1.5 (e2e)</b></td><td>82.4</td><td>83.6</td><td><b>99.9</b></td><td><b>94.1</b></td><td>85.1</td><td>41.8</td><td><b>83.6</b></td><td>88.9</td></tr>
<tr style="background:#a358e5; color:white"><td><b>Falcon OCR 1.5 (pipeline)</b></td><td>80.6</td><td>80.0</td><td>99.8</td><td>93.0</td><td>85.4</td><td>42.2</td><td>75.5</td><td>88.6</td></tr>
</table>

</details>

<details name="benchmarks">
<summary><b>OmniDocBench</b></summary>

Full-page document parsing. Overall↑ aggregates sub-metrics. 1−Edit↑ is text accuracy (higher is better). TEDS↑ measures table structure. CDM↑ evaluates formulas.

<table>
<tr><th>Model</th><th>Overall↑</th><th>1−Edit↑</th><th>TEDS↑</th><th>CDM↑</th></tr>
<tr><td>ovis-ocr-2</td><td><b>95.27</b></td><td><b>97.72</b></td><td>89.26</td><td><b>98.83</b></td></tr>
<tr><td>paddleocr-vl-1.6</td><td>94.95</td><td>96.64</td><td><b>90.24</b></td><td>97.98</td></tr>
<tr><td>glm-ocr</td><td>93.86</td><td>96.64</td><td>87.98</td><td>96.96</td></tr>
<tr><td>mineru2.5-pro</td><td>93.22</td><td>96.70</td><td>85.15</td><td>97.80</td></tr>
<tr><td>unlimited-ocr</td><td>89.60</td><td>92.38</td><td>79.74</td><td>96.70</td></tr>
<tr><td>hunyuan-ocr-1.5</td><td>88.82</td><td>97.36</td><td>75.66</td><td>93.46</td></tr>
<tr><td>dots-mocr</td><td>88.49</td><td>96.61</td><td>73.23</td><td>95.64</td></tr>
<tr><td>chandra-ocr-2</td><td>88.06</td><td>95.96</td><td>72.97</td><td>95.24</td></tr>
<tr><td>deepseek-ocr-2</td><td>83.47</td><td>94.11</td><td>66.47</td><td>89.85</td></tr>
<tr style="background:#a358e5; color:white"><td><b>Falcon OCR 1.5 (pipeline)</b></td><td>93.15</td><td>94.93</td><td>88.53</td><td>96.00</td></tr>
<tr style="background:#a358e5; color:white"><td><b>Falcon OCR 1.5 (e2e)</b></td><td>86.47</td><td>95.47</td><td>69.51</td><td>94.42</td></tr>
</table>

</details>

### Results Analysis

First, a compact model can be competitive when the interface is simple and the training signal is targeted. On olmOCR, Falcon OCR performs strongly on multi-column documents and tables, and is competitive overall against substantially larger systems. Second, evaluation on full-page parsing is sensitive to matching and representation details. On OmniDocBench, the table and formula metrics depend not only on recognition quality but also on how predicted elements are matched to ground truth and how output structure is normalized.

More broadly, these results suggest that an early-fusion single-stack Transformer can be a viable alternative to the common "vision encoder plus text decoder" recipe for OCR. We do not view this as a finished answer, but as a promising direction: one early-fusion backbone, a shared parameter space between text and images, a single decoding interface, and better data and training signals, rather than increasingly complex pipelines. To our knowledge, this is among the first demonstrations that this early-fusion recipe can reach competitive document OCR accuracy at this scale, and we hope it encourages further work in this direction.

## Serving Throughput

Measured on a single A100-80GB GPU with vLLM, processing document images from olmOCR-Bench under high concurrency for optimal vLLM utilization.

<!-- We benchmark two modes to isolate different parts of the pipeline: -->

<!-- - **Cropped regions** — A layout detector is run offline first to extract all regions from every page. Only the resulting crops are sent to the VLLM . This measures pure VLLM throughput with no layout overhead. -->
- **Layout + OCR** — The full end-to-end pipeline: layout detection finds regions on each page, crops them, and vLLM runs OCR on every crop. This represents the real-world serving throughput, inclusive of both layout detection and OCR time.

| Mode | tok/s | img/s | Description |
|------|------:|------:|-------------|
| **Layout + OCR** | 5,825 | 2.9 | Full pipeline: layout detection → crop → per-region OCR |
<!-- | **Plain OCR** | 6,076 | 43.7 | plain OCR, no layout step | -->

At 270M (+30M with layout model) parameters, Falcon OCR is roughly 3× smaller than 0.9B-class OCR VLMs (e.g., PaddleOCR VL), which translates directly into higher serving.

## Limitations

- **Old scans and tiny text**: Heavily degraded scans and very small glyphs remain challenging. These cases often require higher effective resolution and better coverage in the training mixture.
- **Non-unique table representations**: Visually identical tables can be encoded in structurally different HTML forms, which can affect tree-based metrics.
- **Formula matching sensitivity**: LaTeX and Unicode conventions can be penalized differently depending on the benchmark normalization and matching pipeline.

## Examples

### Falcon OCR 1.5

v1.5 improves **real-world captures**, **complex tables**, **handwriting**, and **degraded documents** (faded scans, historical pages) over v1 — while keeping the same 270M early-fusion architecture.

<details name="ocr-examples-v15" open>
<summary><b>Qualitative samples</b></summary>
<p align="center">
  <img src="assets/image.png" width="600" alt="Falcon OCR 1.5 qualitative sample" />
</p>
<p align="center">
  <img src="assets/image%20(1).png" width="600" alt="Falcon OCR 1.5 qualitative sample 2" />
</p>
</details>

### Falcon OCR 1.0

*Click each section below to expand.*

<details name="ocr-examples" open>
<summary><b>Handwriting and Real World Images</b></summary>
<p align="center">
  <img src="https://cdn-uploads.huggingface.co/production/uploads/62fe441427c98b09b503a4e3/51Fj1wxxtAV_jwubml6sa.png" width="600" alt="Handwriting and real world OCR examples" />
</p>
</details>

<details name="ocr-examples">
<summary><b>Tables</b></summary>
<p align="center">
  <img src="https://cdn-uploads.huggingface.co/production/uploads/62fe441427c98b09b503a4e3/2yZjZJAEHVVpd_jfyyDcQ.png" width="600" alt="Table OCR examples" />
</p>
</details>

<details name="ocr-examples">
<summary><b>Formulas</b></summary>
<p align="center">
  <img src="https://cdn-uploads.huggingface.co/production/uploads/62fe441427c98b09b503a4e3/__XMb0GyGO02IPKlQsPQx.png" width="600" alt="Formula OCR examples" />
</p>
</details>

<details name="ocr-examples">
<summary><b>Complex Layout</b></summary>
<p align="center">
  <img src="https://cdn-uploads.huggingface.co/production/uploads/62fe441427c98b09b503a4e3/kTR7nI7ogEqdI1SQtXpTu.png" width="600" alt="Complex layout OCR examples" />
</p>
</details>
---

## vLLM Server
We also provide a Docker-based vLLM-backed inference server capable of serving approximately 6,000 tokens per second.

Single Docker image with two services:

| Service | Default Port | Description |
|---------|-------------|-------------|
| **vLLM** | 8000 | Falcon-OCR vision-language model (OpenAI-compatible API) |
| **Pipeline** | 5002 | Full document parsing: layout detection → crop → OCR → markdown |

The layout model runs inside the pipeline process — it is not a standalone service.

### Quick Start

**Prefer end-to-end parsing** (`skip_layout: true`) for most documents; use layout mode only for very dense pages.

```bash
docker run -d --name falcon-ocr \
  --gpus '"device=0,1"' \
  -e EXPOSED_GPU_IDS=0,1 \
  -e VLLM_GPU=0 \
  -e PIPELINE_GPU=1 \
  -e VLLM_GPU_MEM_UTIL=0.90 \
  -p 8000:8000 \
  -p 5002:5002 \
  ghcr.io/tiiuae/falcon-ocr:latest
```

### API

<details name="api" open>
<summary><b>Health Checks</b></summary>

```bash
curl http://localhost:8000/health      # vLLM
curl http://localhost:5002/health      # Pipeline
```
</details>

<details name="api">
<summary><b>Upload</b> (multipart file upload — images and PDFs)</summary>

The easiest way to send files. Supports images and multi-page PDFs:

```bash
# Single image
curl -X POST http://localhost:5002/falconocr/upload \
  -F "files=@photo.jpg;type=image/jpeg"
# PDF document
curl -X POST http://localhost:5002/falconocr/upload \
  -F "files=@document.pdf;type=application/pdf"
```
</details>

<details name="api">
<summary><b>Parse</b> (recommended — end-to-end, no layout)</summary>

Send the full image directly to the VLM:

```bash
curl -X POST http://localhost:5002/falconocr/parse \
  -H "Content-Type: application/json" \
  -d '{
    "images": ["data:image/jpeg;base64,<...>"],
    "skip_layout": true
  }'
```
</details>

<details name="api">
<summary><b>Parse</b> (layout + OCR — dense pages only)</summary>

Send base64-encoded images for layout detection, cropping, and OCR:

```bash
curl -X POST http://localhost:5002/falconocr/parse \
  -H "Content-Type: application/json" \
  -d '{
    "images": ["data:image/jpeg;base64,<...>"],
    "skip_layout": false
  }'
```

Response:

```json
{
  "json_result": [[{
    "index": 0,
    "mapped_label": "text",
    "content": "The Manuscript",
    "bbox": [273, 273, 937, 380],
    "score": 0.3145
  }]],
  "markdown_result": "The Manuscript",
  "total_output_tokens": 93,
  "processing_time_ms": 414
}
```
</details>

<details name="api">
<summary><b>Direct vLLM</b> (OpenAI-compatible)</summary>

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "falcon-ocr",
    "messages": [{"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,<...>"}},
      {"type": "text", "text": "Extract the text content from this image.\n<|OCR_PLAIN|>"}
    ]}],
    "max_tokens": 2048
  }'
```
</details>

### Configuration

All settings are controlled via environment variables at `docker run` time.

<details name="config" open>
<summary><b>GPU Assignment</b></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_GPU` | `0` | Host GPU ID for the vLLM process |
| `PIPELINE_GPU` | `0` | Host GPU ID for the pipeline (layout model) |
| `EXPOSED_GPU_IDS` | *(all visible)* | Comma-separated host GPU IDs passed via `--gpus` (for index remapping) |
</details>

<details name="config">
<summary><b>Port Assignment</b></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_PORT` | `8000` | Port for the vLLM OpenAI-compatible API |
| `PIPELINE_PORT` | `5002` | Port for the pipeline API |
</details>

<details name="config">
<summary><b>vLLM Tuning</b></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_GPU_MEM_UTIL` | `0.90` | Fraction of GPU memory vLLM can use |
| `MAX_NUM_SEQS` | `2048` | Max concurrent sequences in vLLM |
| `MAX_MODEL_LEN` | `16384` | Max model context length |
| `DTYPE` | `bfloat16` | Model dtype |
| `MAX_NUM_BATCHED_TOKENS` | *(auto)* | Max batched tokens per iteration |
| `CHUNKED_PREFILL` | `false` | Enable chunked prefill |
</details>

<details name="config">
<summary><b>Layout Model Tuning</b></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `LAYOUT_BATCH_SIZE` | `64` | Batch size for layout detection inference |
</details>

<details name="config">
<summary><b>Model Paths</b></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `FALCON_OCR_MODEL` | `/models/Falcon-OCR` | Path to Falcon-OCR VLM weights (inside container) |
| `SERVED_MODEL_NAME` | `falcon-ocr` | Model name exposed by vLLM API |
</details>

### Deployment Modes

<details name="deploy" open>
<summary><b>Two GPUs</b> (best throughput)</summary>

vLLM on one GPU, layout model on another — zero GPU contention:

```bash
docker run -d --name falcon-ocr \
  --gpus '"device=3,4"' \
  -e EXPOSED_GPU_IDS=3,4 \
  -e VLLM_GPU=3 \
  -e PIPELINE_GPU=4 \
  -e VLLM_GPU_MEM_UTIL=0.90 \
  -p 8000:8000 \
  -p 5002:5002 \
  ghcr.io/tiiuae/falcon-ocr:latest
```
</details>

<details name="deploy">
<summary><b>Single GPU</b> (memory sharing)</summary>

Both services share one GPU — tune `VLLM_GPU_MEM_UTIL` to leave room for the layout model:

```bash
docker run -d --name falcon-ocr \
  --gpus '"device=0"' \
  -e EXPOSED_GPU_IDS=0 \
  -e VLLM_GPU=0 \
  -e PIPELINE_GPU=0 \
  -e VLLM_GPU_MEM_UTIL=0.55 \
  -e LAYOUT_BATCH_SIZE=32 \
  -e MAX_NUM_SEQS=512 \
  -p 8000:8000 \
  -p 5002:5002 \
  ghcr.io/tiiuae/falcon-ocr:latest
```
</details>

<details name="deploy">
<summary><b>Custom Ports</b></summary>

```bash
docker run -d --name falcon-ocr \
  --gpus '"device=0,1"' \
  -e EXPOSED_GPU_IDS=0,1 \
  -e VLLM_GPU=0 \
  -e PIPELINE_GPU=1 \
  -e VLLM_PORT=18000 \
  -e PIPELINE_PORT=15002 \
  -p 18000:18000 \
  -p 15002:15002 \
  ghcr.io/tiiuae/falcon-ocr:latest
```

Docker `--gpus "device=3,4"` makes the container see GPUs as local indices `0,1`.
`EXPOSED_GPU_IDS=3,4` allows you to reference host GPU IDs (`VLLM_GPU=3`, `PIPELINE_GPU=4`);
the entrypoint remaps them to the correct container-local indices.
</details>


## Citation

If you use Falcon OCR, please cite:

```bibtex
@article{bevli2026falcon,
  title   = {Falcon Perception},
  author  = {Bevli, Aviraj and Chaybouti, Sofian and Dahou, Yasser and Hacid, Hakim and Huynh, Ngoc Dung and Le Khac, Phuc H. and Narayan, Sanath and Para, Wamiq Reyaz and Singh, Ankit},
  journal = {arXiv preprint arXiv:2603.27365},
  year    = {2026},
  url     = {https://arxiv.org/abs/2603.27365}
}
```