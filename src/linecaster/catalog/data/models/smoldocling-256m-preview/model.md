---
schema: linecaster.model/1
id: smoldocling-256m-preview
version: SmolDocling-256M-preview
source:
  kind: hf
  ref: ds4sd/SmolDocling-256M-preview
pins:
- revision: ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8
  pinned: 2026-11-03
  files:
    assets/SmolDocling_doctags1.png: sha256:2873673cd4ef6417a6fc3cb3df82e7f0190892c80623d0256a64d18836f93bd9
    assets/doctags_v2.png: sha256:e619f976e5a595c5d794bbb446be7bdc71bb94a391e1ebf6b768164039d438b4
    model.safetensors: sha256:cdcdf5d823c5684029c7d8e52177cf10f9034b3aba6577549cfb1a9ce36ad0a2
    onnx/decoder_model_merged.onnx: sha256:c75155e5e121b9d89bf5435d396ccd9e817572d8a0e4589e1c0eb5574bb3c69e
    onnx/decoder_model_merged_bnb4.onnx: sha256:51ef8fa60e201a412c1a0b24333bfa2a6c73d4f45e58b9e2411866cfc6fc707b
    onnx/decoder_model_merged_fp16.onnx: sha256:ccd0761dc1e061c706381fb345a01977d4ec4db2ee97d3acb6886f65fbe2ba81
    onnx/decoder_model_merged_int8.onnx: sha256:9fdce1ec841ad5b730d2c220ff2147f2114cecf7b5518c27cc050c29bf75e997
    onnx/decoder_model_merged_q4.onnx: sha256:ef6045cf8e613277a745f5b56eaf1cc2dda00c64d984acaa005fa5ef706efcc5
    onnx/decoder_model_merged_q4f16.onnx: sha256:e9cda6976be0f2b446a01ace90aa04a520116b4641e544cbc74dd8a70335b606
    onnx/decoder_model_merged_quantized.onnx: sha256:88d2ef3239d292224065443e7dc6a8b87195db94a38280e23bd4b5ca18c1d3b5
    onnx/decoder_model_merged_uint8.onnx: sha256:88d2ef3239d292224065443e7dc6a8b87195db94a38280e23bd4b5ca18c1d3b5
    onnx/embed_tokens.onnx: sha256:816939a02a48a540330655f6cc1a33cb47b2021aec0ebb356a016c50b826f3f6
    onnx/embed_tokens_bnb4.onnx: sha256:7b6ad5d0ac29dc4bd893b61606f760fac40481a4eecbcb318502b05e3562aa37
    onnx/embed_tokens_fp16.onnx: sha256:f08a824993fe5ea9d5affd34a986a3700c4c5cb0fd21993182c03a58c4a0ee3a
    onnx/embed_tokens_int8.onnx: sha256:74e69c670cb770eb3b430c7fdd770a9e4e0f174edef568e6aa67df4276c398e5
    onnx/embed_tokens_q4.onnx: sha256:7b6ad5d0ac29dc4bd893b61606f760fac40481a4eecbcb318502b05e3562aa37
    onnx/embed_tokens_q4f16.onnx: sha256:664289fb111a87112cf97c9ac4d9122119740bc5da3a6eb8305fa1063dec65a4
    onnx/embed_tokens_quantized.onnx: sha256:74e69c670cb770eb3b430c7fdd770a9e4e0f174edef568e6aa67df4276c398e5
    onnx/embed_tokens_uint8.onnx: sha256:74e69c670cb770eb3b430c7fdd770a9e4e0f174edef568e6aa67df4276c398e5
    onnx/vision_encoder.onnx: sha256:9c97aafac0543632c778938e2870afb73a81c7cc3a3e01e84b43a096bd668820
    onnx/vision_encoder_bnb4.onnx: sha256:fcc3b8bf6e0b12be05c5ce66adc5d504fb0efb4a00dbfc53a8f8dbc1cca1516e
    onnx/vision_encoder_fp16.onnx: sha256:f86f88e185e231b91232147206771e267d8ab038aa4e30fb29e376d9ec4db4fb
    onnx/vision_encoder_int8.onnx: sha256:3251860101c63f90c44ec475c874346c461de48421aacc13b5f5741004282240
    onnx/vision_encoder_q4.onnx: sha256:fbcfa73fba2477b564a364123bc066922c9e692a9389c24eb904009f922e9aa0
    onnx/vision_encoder_q4f16.onnx: sha256:c0e3c83edfaf3c946e592f50d9b238eb422c0c4ef62643883a46d7c5ebb7284a
    onnx/vision_encoder_quantized.onnx: sha256:b5e42cf6c8719dba60582c3722cba72673de5e2b739c01e5147bc34d9193ae20
    onnx/vision_encoder_uint8.onnx: sha256:b5e42cf6c8719dba60582c3722cba72673de5e2b739c01e5147bc34d9193ae20
  card: upstream/ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8/README.md
  card_sha256: sha256:9b82c4dd1b38340656da55d628d63bf319c5fc4700811148687b6d8070e7e493
license: CDLA-Permissive-2.0
languages:
- eng
scripts:
- Latn
params: 256M
derived_from:
- ref: HuggingFaceTB/SmolVLM-256M-Instruct
  relation: finetuned
---

SmolDocling-256M-preview is the Docling team's (IBM Research) ultra-compact document conversion VLM (arXiv
2503.11576): it writes a page as DocTags (layout, boxes, tables, code, formulas, charts, captions), which
docling-core turns into a DoclingDocument and from there into Markdown or HTML. It is fine-tuned from
SmolVLM-256M-Instruct; English only. Upstream has superseded it with granite-docling-258M. The repository has
moved: linecaster pins `ds4sd/SmolDocling-256M-preview`, which now redirects to
`docling-project/SmolDocling-256M-preview`. Licence: the card front matter says CDLA-Permissive-2.0, while its
model summary says Apache 2.0; the front matter value is recorded.
The upstream card is in `upstream/ce51f56c4ebe36e0b1c3a55f67b261ba22a50bf8/README.md`.
