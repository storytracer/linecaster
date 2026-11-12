Lossy WebP at quality 80 (libwebp, method 0) at full resolution, 8-bit sRGB: working copies of page images for
publishing and downloads, at a fraction of the working image's size. The colour handling is the working image's (the ICC profile
to sRGB, 16 to 8 bit, alpha onto white) and so are the size limits; image warnings are recorded.

Decoding runs on an NVIDIA GPU where the machine has one and nvImageCodec is installed (`linecaster[nvimgcodec]`):
JPEG (nvJPEG), JPEG 2000 (nvJPEG2000) and TIFF (nvTIFF) in 8-bit gray or RGB; everything else with Pillow. WebP is
always encoded on the CPU (libwebp): no GPU library writes it. Each image records its decoder and encoder.

- `quality` 80: libwebp's quality (Pillow's default).
- `method` 0: libwebp's effort, 0 fast to 6 small (Pillow's default is 4). Speed over size: method 0 encodes several
  times faster at the same quality, with larger files (CHANGELOG.md names the evidence).
- `accel` `auto`: the GPU where it can; `--set image.accel=cpu` decodes with Pillow everywhere.

Editions: 1 used libwebp's default effort (method 4); 2 the fastest (method 0).
