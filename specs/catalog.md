# The catalogue: models, presets, evidence

Status: adopted 2026-11-03. Role models: HTRMoPo v1 and Hugging Face model cards (Markdown with YAML front
matter), OCR-D (functional steps, declared resources, provenance per processing step), Docling (typed options
per engine, one factory per stage), spaCy (versioned registry names that stay resolvable), Datalab's marker,
surya and chandra (configuration declared once, evidence with its source), Daniel van Strien's
`uv-scripts/ocr/models.json` (one catalogue, support levels), ocrscout's profiles (label mappings as data).

## Five documents, one ledger

| Document | Holds | Written by | Format |
|---|---|---|---|
| model | one artifact: source, pinned revisions, file hashes, licence, languages, scripts, lineage; the upstream card verbatim | `linecaster catalog pin` | `models/<id>/model.md` + `models/<id>/upstream/<revision>/…` |
| preset | one engine + one model pin + options, ready to use, with provenance and support level | people | `presets/<id>.md` |
| evidence | one measurement of one preset edition, with its source | runs and people | `evidence/<date>-<preset>-<dataset>.yaml` |
| recipe | a named pipeline, preset ids per step | people | `recipes/*.py` (uv script) |
| run record | what a run resolved: presets with editions and hashes, overrides, software | the run | `OUT/run.yaml`; per page in `ModelInfo` |
| `catalog.lock` | the released preset editions: resolved functional content and its hash | `linecaster catalog release` | `catalog.lock` (YAML) |

Engines are code (`engines/<engine>/`, one package each), not documents.

Model and preset documents are Markdown with YAML front matter: the front matter is data, validated by
`linecaster.catalog.schema`; the body is prose for people (why these settings, limitations, changes). Evidence,
the lock and run records are plain YAML. Bulk data (page rows, exports) stays JSON Lines / Parquet.

## YAML

YAML 1.2 semantics: only `true` / `false` are booleans (no `yes`, `no`, `on`, `off`, so `NO` stays Norwegian),
read with `linecaster.catalog.yamlio`. Quote values that look like numbers or versions (`"1.0"`). Every
document starts with `schema: linecaster.<type>/<n>`. JSON Schemas for editors come from the Pydantic models
(`linecaster catalog schema`).

## Versions: one word for each

| Term | Whose | Meaning | Example |
|---|---|---|---|
| `version` | upstream | what upstream calls it, verbatim, never parsed | `PP-OCRv6 medium`, `Chandra 2` |
| `revision` | upstream | the exact identity of the files | HF commit, version DOI, git commit, sha256 |
| `edition` | linecaster | integer per preset, raised when outputs can change | `edition: 3` |
| `schema` | linecaster | the format of a document | `linecaster.preset/1` |
| release | linecaster | the package version (run records only) | `0.4.0` |

- A tag or branch is resolved to a commit when a model is pinned; the tag is kept as `tag:` for information.
  Zenodo: the version DOI identifies the files, the concept DOI is information. Downloads without a commit:
  the file's sha256 is the revision.
- Model documents carry no linecaster version: a model is its source and its revisions. A new upstream
  revision is a new entry in `pins`, with its own `upstream/<revision>/` folder.
- Preset ids are plain slugs (lowercase, `[a-z0-9.-]`). They may contain upstream names (`deepseek-ocr-2`),
  never our versions. A reference is `id@edition`; `id` alone means the latest edition, but run records always
  store the explicit edition and its hash.

## Released editions are immutable

`linecaster catalog release <id>` writes the current edition's resolved functional content and its sha256 into
`catalog.lock`. Functional content is what can change outputs: `step`, the model pin (`id`, `revision`,
`files`), `engine` (`kind`, `options`), `settings`, `labels` and `serve`. Prose, provenance, support level,
capabilities and limitations are not part of it. `linecaster catalog verify` (and `tests/test_catalog.py`)
fails when a released edition's content changed; such a change is a new edition. Old editions stay
resolvable from the lock (`dots-ocr@1` after the file moved on to edition 2). Unreleased editions are drafts.

## Upstream cards

The original model card is always copied, verbatim, at the pinned revision, whatever its licence: Hugging Face
`README.md`, the HTRMoPo record, a repository README; a separate licence file next to it. Its sha256 is in the
pin. Cards are never edited; licence, languages and scripts in `model.md` are taken from them where they say.

## Steps, capabilities, labels

Steps (`STEPS`): `layout`, `lines`, `recognition`, `tables`, `formulas`, `page` (end to end: a whole page in,
text out). Recognition reads a `unit`: `line` (kraken, PaddleX, Tesseract) or `region` (a VLM per layout
region). OCR-D's functional steps are mapped in `OCRD_STEPS` for METS agents.

What depends on the code belongs to the engine (`Engine.capabilities`): e.g. kraken gives word boxes with
confidences. What depends on the weights belongs to the model or preset: languages (ISO 639-3), scripts
(ISO 15924), output format. A preset's `capabilities.produces` uses the vocabulary `PRODUCES`.

Layout presets map their native labels to DoclingDocument labels (`docling_core.types.doc.DocItemLabel`) in
`labels:`; unmapped labels are `text`.

## Engines

An engine is a class registered under a versioned kind in the entry-point group `linecaster.engines`
(`kraken.recognition/1 = linecaster_kraken:KrakenRecognitionModel`). It declares `kind`, `step`, `Options`
(a Pydantic model whose fields have descriptions; the recipe CLI, `linecaster engines` and the docs come from
it) and `capabilities`. A backward-incompatible change of options is a new kind (`/2`); the old one stays
registered. Each package that ships catalogue documents registers its catalogue directory in the entry-point
group `linecaster.catalog`.

## Evidence

One measurement per file: `preset: id@edition`, `source` (`own-run`, `board`, `card-claim`,
`vendor-benchmark`), `dataset: repo@revision`, `metrics`, `hardware`, `software` (linecaster commit, server
version), `run`, `date`, `notes`. Claims are never measurements; the docs show the source of every number.

## Support

`core` (maintained, validated), `experimental` (works, may change), `legacy` (kept resolvable;
`superseded_by:` names the replacement).
