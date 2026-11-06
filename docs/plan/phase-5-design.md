# Phase 5 design (working document)

Interfaces for phase 5 of [the plan](refactoring.md): the docs. Removed with the plan when the refactoring is done.
Terms are the [glossary](../reference/glossary.md)'s. No behavior changes: outputs, flags (except the docs command)
and APIs stay as they are; code changes are docstrings, class metadata the generator reads, and the generator.

## 1. One generator, one command

- `linecaster docs [--out docs] [--readme README.md] [--check]` replaces `linecaster catalog docs`. It writes every
  generated file: the catalog pages (`docs/catalog/`, as today), the block pages (§2), the README's tables between
  their markers, `docs/index.md` for the site (§6) and `docs/llms.txt` / `docs/llms-full.txt`.
- `--check` writes nothing and exits with 1, naming
  each file that differs from a fresh generation. A test runs the check (docs currency).
- Generated files start with a one-line HTML comment that says they are generated and by which command.

## 2. Block pages

- `docs/blocks/README.md` (index: one table per family, `| Block | What it does |`, the docstring's summary line)
  and `docs/blocks/<family>/<Block>.md` for every public block (the classes exported from `linecaster.blocks.*`;
  base classes get a section on the index page, not pages of their own).
- Family = the package under `blocks/` (readers, layout, lines, recognition, conversion, text, composition,
  binding, validation, servers, writers, composites).
- Page, every row from code: title, family, module, one-line summary; a key-value table: unit (in, out), reads,
  adds, replaces (from `contract()` of an instance built with the defaults or, where a block needs arguments, with
  the example arguments the block declares for docs), backends (model blocks: in-process, served, chat as
  applicable), the catalog step and its presets (model and rule blocks: links to the preset pages), comes after /
  comes before (derived: the blocks whose adds cover its reads, and those that read what it adds), used in (the
  pipeline scripts that construct it, found with `ast`), source (a link); the options table (constructor
  arguments: name, type, default, description from `Args:`); the behavior (the docstring body); a small Mermaid
  diagram (reads → block → adds); the example (the docstring's `Example:`, if any).
- README: the hand-written block tables in "Post-processing" and "Input, output and servers" become one generated
  section between `<!-- blocks:start -->` / `<!-- blocks:end -->` (family, block, summary, link), like the catalog
  tables.

## 3. Docstrings

- The standard, in `docs/reference/conventions.md` ("Docstrings"): Google style. Summary line: what the block (or
  function) does, present tense, starting with a verb, one sentence. Body: the contract in words, edge cases, what
  it records. `Args:` for every constructor or function argument (meaning, effect of the default, constraints;
  datatrove's inherited reader/writer arguments in one line). `Example:` required for `runtime.run.main`, the
  catalog API (`linecaster.catalog` public functions), the serializers (`to_alto`, `from_alto`, ...) and `build()`;
  optional for blocks. Engine options stay pydantic `Field(description=...)`.
- An `ast` test (no new dependency) checks: every public block, built-in engine class, backend, serializer,
  `build`, `run_pages` and `runtime.run.main` has a docstring with a summary line, and its `Args:` names every
  parameter of the signature (constructor for classes) and no parameter that does not exist.
- Write the missing docstrings now; fix stale ones.

## 4. Reference docs and CLAUDE.md

- `CLAUDE.md` becomes rules only, each a short "rule. Reason." with no status line and no history; it points to
  `docs/reference/` for everything descriptive. The architecture prose it holds today moves to
  `docs/reference/architecture.md` (blocks, backends, servers, engines, pipeline scripts, executors, the run
  layout, Jobs) unless `pipelines.md` / `catalog.md` already say it; nothing is lost, nothing is said twice.
- `docs/reference/compatibility.md`: what counts as a breaking change (block names and arguments, backends, CLI
  commands and flags, pipeline ids and slots, page record and item record fields and schema ids, the run layout,
  catalog ids, editions and the lock format, engine ids and options); while the version is 0.x there is no
  deprecation period and no aliases, every breaking change is an upgrade note in `CHANGELOG.md`; released catalog
  editions never change (migrations keep `previous_sha256`).
- Engine packages (`engines/*/README.md`): minimal, what the package provides, its engines (links to their
  generated pages) and that presets live in linecaster's catalog.

## 5. Evidence tables

- The evidence tables on preset and recipe pages gain Hardware and Backend columns (from the evidence record's
  `hardware` and `software.backend`), so rows that differ only there stop looking like duplicates. Measurements
  that live in preset prose and have a source move into evidence records where the schema allows (no edition
  change: evidence is not part of an edition's hash; check that before moving anything, and leave it if it is).

## 6. The site

- MkDocs with Material: `mkdocs.yml` at the root, `docs_dir: docs`, a dependency group `docs`
  (`mkdocs>=1.6,<2`, `mkdocs-material>=9.6,<10`), not an extra. `uv run --group docs mkdocs build --strict`
  builds it into `site/` (gitignored). No deployment in this phase (no CI yet; phase 6).
- Nav: Home (`docs/index.md`, generated from the README with its links rewritten for the site), Reference
  (the hand-written `docs/reference/` pages), Blocks, Catalog (engines, models, presets, pipelines, recipes),
  Changelog. `docs/plan/` is excluded from the site.
- Links that leave `docs/` (source files, the root README, pipelines/) are written as GitHub links
  (`https://github.com/storytracer/linecaster/blob/main/...`) in generated pages and in `docs/index.md`; the
  hand-written reference pages are fixed so `--strict` passes.
- `llms.txt` (llmstxt.org format: title, summary, sections of links to the pages' Markdown) and `llms-full.txt`
  (README, the reference pages, the glossary, the block index and the catalog index, concatenated), written by
  `linecaster docs` into `docs/` so the site serves them at its root.

## 7. Tests

- Docs currency: `linecaster docs --check` passes (one test).
- The README's "Your own pipeline" snippet: a test extracts the Python block and runs it to the point where the
  plan is built and checked (`build(...).check()`), with fake CPU engines where it would load models; shell blocks
  are not run.
- The docstring test (§3).

## Checks (lean)

The full suite once at the end; `linecaster docs --check`; `uv run --group docs mkdocs build --strict` once;
`linecaster catalog verify`. No goldens run unless code other than docstrings, class metadata and the docs
generator changed.
