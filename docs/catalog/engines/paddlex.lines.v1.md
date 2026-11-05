# paddlex.lines.v1

*Engine · lines · package `linecaster-paddlex`*

linecaster engine model for the lines step: PP-OCRv6 detection on the whole page (default) or,
with `per_region`, on each region's crop. Fills `Transcription.lines` with geometry (polygon,
bbox, score); text stays `None`. Replaces any lines already present. The model files: `weights` (a
catalogue pin) or the catalogue's newest pin for `model_name` (`weights.resolve`).

|  |  |
|---|---|
| Class | `linecaster_paddlex:PaddleLineEngine` |
| Source | [detector.py](../../../engines/paddlex/src/linecaster_paddlex/detector.py) |
| Reads | pages |
| Produces | lines |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `model_name` | `str` | `'PP-OCRv6_medium_det'` | PaddleX text detector: PP-OCRv6_{tiny,small,medium}_det |
| `device` | `str` | `'auto'` | auto, cpu, cuda, tensorrt or coreml (ONNX Runtime providers) |
| `per_region` | `bool` | `False` | detect on each region's crop instead of the whole page |
| `unclip_ratio` | `float` | `1.5` | how far the DB boxes are grown around the text kernel (PaddleOCR's default 1.5) |
| `box_thresh` | `float` | `0.6` | minimum mean score of a box |
| `thresh` | `float` | `0.3` | binarisation threshold of the probability map |
| `pad` | `int` | `0` | per_region: pixels around a region's crop |
| `mask` | `bool` | `False` | per_region: paint everything outside the region polygon white |

## Presets

- [`pp-ocrv6-medium-det`](../presets/lines/pp-ocrv6-medium-det.md)
- [`pp-ocrv6-small-det`](../presets/lines/pp-ocrv6-small-det.md)
- [`pp-ocrv6-tiny-det`](../presets/lines/pp-ocrv6-tiny-det.md)
