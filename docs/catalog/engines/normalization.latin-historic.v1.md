# normalization.latin-historic.v1

*Engine · normalization · package `linecaster`*

The explicit mapping table of `linecaster.text.variants` for historic Latin print: long s, ligatures, r
rotunda and superscript e over a, o, u folded; æ, œ, ø, å and ß stay; NFC, never NFKC; spelling is never
modernized.

|  |  |
|---|---|
| Class | `linecaster.engines:LatinHistoricNormalizationEngine` |
| Source | [normalization.py](../../../src/linecaster/engines/normalization.py) |
| Reads | pages |
| Produces | normalized |
| Scripts | Latn |
| Runs | in the pipeline's process |
