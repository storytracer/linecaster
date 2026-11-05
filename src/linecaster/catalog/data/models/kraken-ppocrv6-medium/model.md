Benjamin Kiessling's PP-OCRv6 (medium) line recognizer for kraken (ALMAnaCH, Inria Paris), as mirrored byte for
byte on the Hugging Face Hub by Small Models for GLAM; the canonical release is the Zenodo record
[10.5281/zenodo.21788410](https://doi.org/10.5281/zenodo.21788410), which is provenance only: linecaster always downloads from the mirror (Zenodo
throttles). License, languages (44 plus `mul`) and scripts are the card's.

The card describes the model as trained from scratch by kraken's author on line images of historical,
contemporary and born-digital documents, handwritten and printed, on an architecture adapted from PaddlePaddle's
PP-OCRv6 (128 px line height, uncapped line width, Adam+Muon); it is not a conversion of PaddleOCR's
`PP-OCRv6_medium_rec` weights, so `derived_from` names only the mirror relation. kraken's own code runs it
(`kraken.recognition.v1`), on torch; the model was trained in bf16-mixed, which is why linecaster's presets run it
in bf16-mixed on CUDA.
