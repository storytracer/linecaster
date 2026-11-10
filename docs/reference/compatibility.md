# Compatibility

What linecaster keeps stable for derivatives, pipelines and stored outputs, and how a change that breaks it is
announced. Terms are the [glossary](glossary.md)'s.

## What counts as a breaking change

A change is breaking when code, a command line, a stored file or a catalog reference that worked before stops
working or starts to mean something else:

| Surface | Breaking | Not breaking |
|---|---|---|
| blocks | a block renamed or removed; a constructor argument renamed, removed or made required; a default that changes what a run writes | a new block; a new argument whose default keeps the old behavior |
| backends | `InProcess`, `Served`, `Chat` renamed or removed, or an argument as for blocks | a new argument with a default that keeps the old behavior |
| commands and flags | a `linecaster` command or a pipeline script's option renamed, removed, or given another meaning or default | a new command or option |
| pipeline ids and slots | a pipeline id or a slot renamed or removed, a slot's step changed | a new pipeline script; a new slot that can stay empty |
| page records and item records | a field renamed, removed or given another meaning; a schema id (`linecaster.page/2`) whose records a reader no longer reads | a new optional field; a new schema version that `PageRecordReader` reads together with the older ones |
| the run layout | a folder or file name under `OUT` (`pages/`, `rejects/`, `logs/`, `traces/`, `run.yaml`) or its format changed | a new file or folder |
| the catalog | a catalog id (model, preset, recipe) renamed or removed; a released edition changed; the lock format changed without a migration | a new entry or edition; a catalog migration that keeps every output |
| engines | an engine id removed; an option renamed or removed, or a default changed (a new code id, `.v2`, instead) | a new engine; a new option whose default keeps the old behavior (the same id) |

Internal modules and names with a leading underscore, log messages, stats and the generated docs are not part of
it.

## While the version is 0.x

There is no deprecation period and there are no aliases: a breaking change takes effect in the release that makes
it, and every breaking change is an upgrade note in `CHANGELOG.md` (what changed, who is affected, what to do),
listed first.

## Versions and releases

Versions follow semantic versioning, with the 0.x convention that the minor number does what the major one does
from 1.0 on. What a change bumps follows from the table above:

| Change | While 0.x | From 1.0 |
|---|---|---|
| breaking (any surface above; it needs an upgrade note) | minor (0.3.2 → 0.4.0) | major |
| new blocks, options, presets, recipes, commands or features that keep the old behavior | patch | minor |
| fixes, performance, corrections of the docs | patch | patch |

A release bumps by its largest change. Ranges such as the engine packages' `linecaster>=0.1,<0.4` then hold: every
release inside them keeps what worked.

- **When:** at the end of a finished piece of work that changes behavior, once it is merged into `main` and CI is
  green; one release per piece of work, not per commit. A commit that changes only the README is no release; other
  docs wait for the next release unless they correct something wrong.
- **How:** the version in `pyproject.toml` and `linecaster.__version__` (`tests/test_version.py` checks they agree),
  `CHANGELOG.md`'s Unreleased section as `## <version> (<date>)`, the scripts relocked, an annotated tag
  `v<version>`, pushed (the docs workflow publishes `<major>.<minor>`). A minor bump while 0.x (a major one from 1.0)
  also widens the engine packages' linecaster range to the next one and bumps each engine package's patch version.
- **Engine packages** version on their own by the same table, applied to their engines (ids, options, defaults).
- **1.0.0** is the maintainer's decision: from then on breaking changes get a deprecation period. No release reaches
  it on its own.

## Released catalog editions

A released edition never changes ([catalog](catalog.md#released-editions-are-immutable)): a change that can change
outputs is a new edition, and the old one stays resolvable from the lock. A catalog migration (a change of the
catalog's vocabulary or format that keeps every output) recomputes an edition's hash and keeps the old one as
`previous_sha256`, so run records written before it still resolve. Engine and pipeline code ids follow the same
rule: an incompatible change of options or slots is a new id, and the old one stays registered.
