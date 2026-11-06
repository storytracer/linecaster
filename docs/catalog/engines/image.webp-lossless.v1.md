# image.webp-lossless.v1

*Engine · image · package `linecaster`*

The working image (`linecaster.images.convert.to_working_webp`): any Pillow-supported page image
decoded, 8-bit sRGB with its ICC profile applied, encoded as lossless WebP at full resolution (method 0,
exact). Pages over WebP's or Pillow's size limit raise `ImageTooLarge` before decoding. Takes the page
image's bytes and returns the WebP bytes with their record (size, hashes, decoder).

|  |  |
|---|---|
| Class | `linecaster.engines:WebpLosslessImageEngine` |
| Source | [image.py](../../../src/linecaster/engines/image.py) |
| Reads | pages |
| Produces | image |
| Scripts | all |
| Runs | in the pipeline's process |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `effort` | `int` | `80` | libwebp's lossless compression effort (Pillow's quality): size and speed, never pixels |

## Presets

- [`working-image`](../presets/image/working-image.md)
