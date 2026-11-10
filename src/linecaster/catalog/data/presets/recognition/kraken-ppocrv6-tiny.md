kraken's PP-OCRv6 tiny recognizer through kraken's own code (`RecognitionTaskModel`), on every line of the
page in the line step's order.

- `batch_size` 8. kraken pads a batch to its widest
  line, so the batch size can move numerics; one page per request, batching only within the page.
- `precision` auto: bf16-mixed on CUDA (the model was trained in bf16-mixed), 32-true on the CPU. Needs the
  kraken fork with the inference autocast fix (storytracer/kraken 3d235ee8); on upstream kraken 7.1 the setting is
  inert.
  T4-class GPUs have no bf16 tensor cores: use 16-mixed or 32-true there (a new preset).
- `text_direction` horizontal-lr; right-to-left material wants horizontal-rl.
- The card says tiny and small trade accuracy for speed and memory.
