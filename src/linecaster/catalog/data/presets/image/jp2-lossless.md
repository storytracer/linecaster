Lossless JPEG 2000 (the reversible 5/3 wavelet, colour transform on, JP2 container) at full resolution, 8-bit sRGB,
with the working image's colour handling and size limits; image warnings are recorded. The pixels decode exactly to
the converted image's.

Decoded and encoded on an NVIDIA GPU where the machine has one and nvImageCodec is installed (`linecaster[nvimgcodec]`,
nvJPEG2000); else with Pillow (OpenJPEG). Each image records its decoder and encoder.

- `lossless`: the reversible wavelet; `--set image.lossless=false --set image.psnr=40` gives lossy JPEG 2000 at a
  target PSNR.
- `accel` `auto`: the GPU where it can.
