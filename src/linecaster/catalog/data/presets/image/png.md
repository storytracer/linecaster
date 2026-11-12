PNG (zlib level 6) at full resolution, 8-bit sRGB, with the working image's colour handling and size limits; image
warnings are recorded. Lossless: the pixels decode exactly to the converted image's.

Decoded on an NVIDIA GPU where the machine has one and nvImageCodec is installed (`linecaster[nvimgcodec]`), else with
Pillow; PNG is always encoded on the CPU (libpng's zlib through Pillow): no GPU library writes it.

- `compress_level` 6: zlib's level (Pillow's default), 0 to 9: size and speed, never pixels.
- `accel` `auto`: the GPU where it can.
