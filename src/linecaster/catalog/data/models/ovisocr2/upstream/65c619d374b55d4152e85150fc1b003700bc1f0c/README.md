---
license: apache-2.0
library_name: transformers
pipeline_tag: image-text-to-text
base_model: Qwen/Qwen3.5-0.8B
tags:
- ocr
- document-parsing
- multimodal
- markdown
- tables
- formulas
- vllm
- qwen3_5
---

# OvisOCR2

<p align="center">
  <img src="https://cdn-uploads.huggingface.co/production/uploads/658a8a837959448ef5500ce5/vRCIu5QD8VuIJolkC_ZHQ.png" alt="Ovis" width="30%" />
</p>

<p align="center">
  <a href="https://arxiv.org/abs/2607.13639">Technical Report</a>
  &nbsp;|&nbsp;
  <a href="https://huggingface.co/spaces/ATH-MaaS/OvisOCR2">Online Demo</a>
</p>

## Introduction

We are pleased to announce the release of OvisOCR2, a compact 0.8B end-to-end model for page-level document parsing. Given a document page image, OvisOCR2 generates a Markdown representation in natural reading order, covering text, formulas, tables, and visual regions.

OvisOCR2 is developed by post-training Qwen3.5-0.8B using a carefully designed data engine that combines real-world and synthetic data, together with a multi-stage training recipe integrating SFT, RL, and OPD. The model delivers strong document parsing performance while maintaining a small deployment footprint.

OvisOCR2 achieves an overall score of 96.58 on OmniDocBench v1.6, establishing a new state of the art and **becoming the first end-to-end model to top this leaderboard previously dominated by pipeline methods**. On PureDocBench, OvisOCR2 also achieves the highest Avg3 score of 75.06.

<p align="center">
  <img src="./performance.png" alt="Performance of OvisOCR2 on OmniDocBench v1.6" width="100%" />
</p>

## Performance

<p align="center">
  <img src="./performance_omnidocbench_v16.png" alt="OmniDocBench v1.6 comparison" width="100%" />
</p>

<p align="center">
  <img src="./performance_puredocbench.png" alt="PureDocBench comparison" width="100%" />
</p>

## Inference

```bash
pip install "vllm==0.22.1" pillow
```

```python
from PIL import Image
from vllm import LLM, SamplingParams


class OvisOCR2Parser:
    def __init__(self, model_name_or_path: str):
        self.model = LLM(
            model=model_name_or_path,
            tensor_parallel_size=1,
            gpu_memory_utilization=0.8,
            gdn_prefill_backend="triton"
        )

        prompt = '\nExtract all readable content from the image in natural human reading order and output the result as a single Markdown document. For charts or images, represent them using an HTML image tag: <' + 'img src="images/bbox_{left}_{top}_{right}_{bottom}.jpg" />, where left, top, right, bottom are bounding box coordinates scaled to [0, 1000). Format formulas as LaTeX. Format tables as HTML: <table>...</table>. Transcribe all other text as standard Markdown. Preserve the original text without translation or paraphrasing.'
        self.prompt = self.model.get_tokenizer().apply_chat_template(
            [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False
        )

        self.sampling_params = SamplingParams(
            max_tokens=16384,
            temperature=0.0
        )

    def _clean_truncated_repeats(
        self,
        text: str,
        min_text_len: int = 8000,
        max_period: int = 200,
        min_period: int = 1,
        min_repeat_chars: int = 100,
        min_repeat_times: int = 5
    ) -> str:
        n = len(text)
        if n < min_text_len:
            return text

        max_period = min(max_period, n - 1)
        for unit_len in range(min_period, max_period + 1):
            if text[n - 1] != text[n - 1 - unit_len]:
                continue

            match_len = 1
            idx = n - 2
            while idx >= unit_len and text[idx] == text[idx - unit_len]:
                match_len += 1
                idx -= 1

            total_len = match_len + unit_len
            repeat_times = total_len // unit_len
            tail_len = total_len % unit_len

            if repeat_times >= min_repeat_times and total_len >= min_repeat_chars:
                return text[: n - total_len + unit_len] + text[n - tail_len:]

        return text

    def parse(self, images: list[Image.Image], filter_imgtags: bool = True) -> list[str]:
        vllm_inputs = [
            {
                "prompt": self.prompt,
                "multi_modal_data": {"image": image},
                "mm_processor_kwargs": {
                    "images_kwargs": {
                        "min_pixels": 448 * 448,
                        "max_pixels": 2880 * 2880
                    }
                }
            }
            for image in images
        ]

        outputs = self.model.generate(vllm_inputs, self.sampling_params)

        markdowns = []
        for output in outputs:
            text = output.outputs[0].text.strip()
            if filter_imgtags:
                text = "\n\n".join(
                    block
                    for block in text.split("\n\n")
                    if not block.strip().startswith('<img src="images/bbox_')
                )
            markdowns.append(self._clean_truncated_repeats(text))

        return markdowns


if __name__ == "__main__":
    parser = OvisOCR2Parser("ATH-MaaS/OvisOCR2")
    images = [Image.open("test1.jpg"), Image.open("test2.jpg")]
    markdowns = parser.parse(images)
    print(markdowns[0])
```

By default, `parse` removes HTML image tags for visual regions. To render Markdown with visual regions, set `filter_imgtags=False` and save the Markdown file together with the referenced image crops as follows:

```python
import re
from pathlib import Path

from PIL import Image


BBOX_IMAGE_PATTERN = re.compile(
    r'<img src=' + r'"images/bbox_(\d+)_(\d+)_(\d+)_(\d+)\.jpg" />'
)


def save_renderable_markdown_with_visual_regions(
    markdown: str,
    page_image: Image.Image,
    output_dir: str,
) -> None:
    output_dir = Path(output_dir)
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    width, height = page_image.size
    for left, top, right, bottom in BBOX_IMAGE_PATTERN.findall(markdown):
        x1 = max(0, min(width, round(int(left) * width / 1000)))
        y1 = max(0, min(height, round(int(top) * height / 1000)))
        x2 = max(0, min(width, round(int(right) * width / 1000)))
        y2 = max(0, min(height, round(int(bottom) * height / 1000)))
        if x2 <= x1 or y2 <= y1:
            continue

        crop_path = images_dir / f"bbox_{left}_{top}_{right}_{bottom}.jpg"
        page_image.crop((x1, y1, x2, y2)).convert("RGB").save(crop_path)

    (output_dir / "output.md").write_text(markdown, encoding="utf-8")


parser = OvisOCR2Parser("ATH-MaaS/OvisOCR2")
page_image = Image.open("test1.jpg")
markdown = parser.parse([page_image], filter_imgtags=False)[0]
save_renderable_markdown_with_visual_regions(markdown, page_image, "output")
```

## Citation

If you find OvisOCR2 useful, please consider citing our technical report:

```bibtex
@article{lu2026ovisocr2,
  title={OvisOCR2 Technical Report},
  author={Shiyin Lu and Yinglun Li and Yu Xia and Yuhui Chen and An-Yang Ji and Jun-Peng Jiang and Qing-Guo Chen and Jianshan Zhao and En Lin and Haijun Li and Cheng Qin and Zhao Xu and Weihua Luo},
  journal={arXiv preprint arXiv:2607.13639},
  year={2026}
}
```

## License

This project is licensed under the [Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0.txt) (SPDX-License-Identifier: Apache-2.0).

## Disclaimer

We used filtering and quality-assurance procedures during data construction to reduce parsing errors such as repeated outputs, incomplete content, invalid table/formula structures, and reading-order inconsistencies. Due to the diversity and complexity of real-world documents, OvisOCR2 may still produce incorrect or incomplete outputs. Please manually verify results in critical applications.
