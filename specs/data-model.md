# Data model decisions (overnight 2026-11-03, for review)

Decisions taken while building the first version, with the reason for each. Open for review.

1. **`regions` is a third primary part next to `docling` and `lines`.** The EBDC deck's PageOCR has two
   primary parts (`docling`, `lines`). Free combination of steps needs a layout contract that exists
   before any text: a line step and a recogniser read regions (label, polygon, reading order, score)
   long before a DoclingDocument can be built. `docling` stays the assembled document (built from
   regions + lines by an assembly step); `regions` is the contract between steps. Region ids are the
   producer's own (PP-DocLayout: `<raw label>_<index>`, orphan rows: `orphan_<n>`), and lines refer
   to them with `region_id`.
2. **Coordinates keep the producer's precision.** Polygons and baselines are float lists exactly as
   the engine returned them; `bbox` is `[x, y, width, height]` for readers, but algorithms derive
   boxes from the polygon (`geometry.bbox_of`) so their arithmetic matches the engine's (no
   `x + width` rounding).
3. **A line's `text` is `None` until a recogniser ran** (empty string = recognised as empty). Lines
   carry `reading_order` (page rank) and `row` (visual row within the region).
4. **Words are the finest level.** kraken's character cuts become words in the kraken backend with
   kraken's own rule (split at whitespace, a word's box = the bounding box of its cuts), so word
   boxes match kraken's serialiser.
5. **`model` is a list of `ModelInfo`, one per step that ran** (step, name, revision, backend,
   settings, measurements), so a composed chain records every model it used.
6. **A page is one datatrove `Document`**: `id` = page_id, `text` = the primary transcription's text,
   image bytes in `media[0]`, the page row under `metadata["page"]`.
7. **Processing order vs reading order.** The list order of `Transcription.lines` after the line
   steps is the order a recogniser processes (and batches) lines: regions in the layout step's order,
   orphan rows last, rows within each region — exactly squiddleocr's order, so batches are composed
   the same way. `reading_order` is the separate reading rank (regions by reading order, then rows).

## Environment lesson (2026-11-03)

`[tool.uv.sources]` applies only to a project's own dependencies. The engine environment listed the
kraken fork as a source, but kraken came in transitively (through `linecaster-kraken`), so uv
resolved upstream kraken 7.1.1, whose `--precision` is inert: the chain silently ran fp32 and 69 of
1,560 lines differed from squiddleocr's bf16 goldens. Fix: kraken is a direct dependency of
`envs/kraken-paddlex`, and the numerically relevant versions are pinned with
`constraint-dependencies` to the ones the goldens were recorded with. After the fix the
block-composed chain (in-process) reproduces squiddleocr's goldens exactly on the 60-page sample:
1,560/1,560 lines identical in line box, text and word boxes.
