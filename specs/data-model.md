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
