# Phase 4 design (working document)

Interfaces for phase 4 of [the plan](refactoring.md): VLMs as a backend, converters, the single-region layout as an
engine, skeletons for IIIF Collections and PDF items. Removed with the plan when the refactoring is done. Terms are
the [glossary](../reference/glossary.md)'s. Outputs stay byte-identical (the goldens; one VLM page run compared
old vs new with a fake OpenAI-compatible server).

## 1. VLMs as the `chat` backend

- `linecaster.backends.Chat(preset: str, endpoint: str | None = None, ...)`: the third backend next to `InProcess` and
  `Served`, for page and region presets of the chat engine (`chat.v1`); it carries what `ChatAdapter`, the window
  and the read timeout need today. `to_dict`, `warm_up`, secrets (`api_key=EnvVar(...)`) as the other backends.
- `PageRecognizer(backend: Chat, ...)` and `RegionRecognizer(backend: Chat, labels=..., ...)` become `ModelBlock`s
  with the `chat` backend: the served streaming code (saturate's window, `through()`, errors per page, observers'
  `on_unit` events) exists once, in `ModelBlock`; `blocks/recognition/chat.py` keeps only what is specific to chat
  (building the messages through the adapter, region crops, parsing).
- `ChatModelServer` unchanged. `transcribe_vlm.py` builds the same pipeline through the new classes.

## 2. Converters

- `TranscriptionConverter(format="auto"|"alto"|"page"|"hocr"|"text", source="media"|"uri", transcription="ocr_original",
  uri_key=None)` (conversion family): reads a library's own OCR delivered with the page (a document media, as the
  `ManifestReader` adds it, or a file named by a URI in the page record) with linecaster's `from_alto` / `from_page`
  / `from_hocr` / plain text, at the page image's size; adds `ocr_original:*`; failures are per-page errors.
- `ManifestReader(existing_ocr=True)` only fetches the OCR bytes (as a document media); the pipeline puts a
  `TranscriptionConverter` after it (the builder inserts one when the reader brings OCR media and none follows).

## 3. The single-region layout

- `layout.single-region.v1` (built-in engine, in-process only): one `text` region per page covering the image
  (today's `SingleRegionLayout` logic); preset `single-region@1`. `LayoutDetector("single-region@1")` replaces the
  block `SingleRegionLayout` (removed); `transcribe_modular.py --layout single-region@1` instead of any special flag.

## 4. Skeletons

- IIIF Collections: pybookget `read_collection(data) -> list[CollectionEntry(id, label, kind="manifest"|"collection")]`
  (and `detect_format` returns `"iiif-collection"`); `ManifestReader` expands a collection entry into its manifests
  (recursively, with a depth limit) as items. Implemented far enough for one level with tests; nested collections
  and paging (`first`/`next`) raise `NotImplementedError` with a clear message, tests marked xfail.
- PDF items: `PdfReader(data_folder, paths_file=None, glob_pattern="**/*.pdf", dpi=300, ...)` (readers family, extra
  `[pypdfium2]`): one item per PDF, one page per PDF page rendered to an image (and, later, the PDF's own text layer as
  `ocr_original`). Skeleton: the class, its contract, the extra, the rendering of a page via pypdfium2; the text layer
  `NotImplementedError`, tests marked xfail.
