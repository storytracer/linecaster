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

## Released catalog editions

A released edition never changes ([catalog](catalog.md#released-editions-are-immutable)): a change that can change
outputs is a new edition, and the old one stays resolvable from the lock. A catalog migration (a change of the
catalog's vocabulary or format that keeps every output) recomputes an edition's hash and keeps the old one as
`previous_sha256`, so run records written before it still resolve. Engine and pipeline code ids follow the same
rule: an incompatible change of options or slots is a new id, and the old one stays registered.
