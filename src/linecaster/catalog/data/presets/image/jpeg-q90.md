JPEG at quality 90, 4:2:0 chroma, optimized Huffman tables, full resolution, 8-bit sRGB, with the working image's
colour handling and size limits; image warnings are recorded.

Decoded on an NVIDIA GPU where the machine has one and nvImageCodec is installed (`linecaster[nvimgcodec]`), and
encoded there too (nvJPEG); else with Pillow (libjpeg-turbo). A GPU and a CPU encoder write different bytes at the
same quality: each image records its encoder, and `--set image.accel=cpu` keeps both steps on the CPU.

- `quality` 90: the encoder's quality, 0 to 100.
- `accel` `auto`: the GPU where it can.
