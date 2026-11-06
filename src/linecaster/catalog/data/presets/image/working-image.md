The working image: any page image Pillow decodes, as 8-bit sRGB (its ICC profile applied, alpha flattened onto
white) in lossless WebP at full resolution, method 0, exact, so the pixels the models see are the delivered ones.
Pages over WebP's size limit (16,383 pixels a side) or Pillow's decompression-bomb threshold are refused from the
header, before decoding, and go to `rejects/`.

- `effort` 80: libwebp's lossless compression effort (Pillow's `quality`); it changes the file size and the time,
  never the pixels.
