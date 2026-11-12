Lossy WebP at quality 80 (libwebp, method 4) at full resolution, 8-bit sRGB: for page images that are published
or downloaded, at a fraction of the working image's size. The colour handling is the working image's (the ICC profile
to sRGB, 16 to 8 bit, alpha onto white) and so are the size limits; image warnings are recorded.

Decoding runs on an NVIDIA GPU where the machine has one and nvImageCodec is installed (`linecaster[nvimgcodec]`):
JPEG (nvJPEG), JPEG 2000 (nvJPEG2000) and TIFF (nvTIFF) in 8-bit gray or RGB; everything else with Pillow. WebP is
always encoded on the CPU (libwebp): no GPU library writes it. Each image records its decoder and encoder.

- `quality` 80: libwebp's quality (Pillow's default).
- `method` 4: libwebp's effort (Pillow's default), 0 fast to 6 small.
- `accel` `auto`: the GPU where it can; `--set image.accel=cpu` decodes with Pillow everywhere.
