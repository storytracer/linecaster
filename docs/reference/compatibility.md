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
| data formats (page records, documents, run records, evidence, benchmarks, scores, samples) | a field renamed, removed or given another meaning (a new format version, `linecaster.page/5`); a format version a reader no longer reads | a new optional field (the version stays); a new version that its readers read together with the older ones, upgraded on load |
| the run layout | a folder or file name under `OUT` (`pages/`, `rejects/`, `logs/`, `traces/`, `run.yaml`) or its format changed | a new file or folder |
| the catalog | a catalog id (model, preset, recipe, policy, conventions) renamed or removed; a field of an entry's file renamed or removed | a new entry; a change of what an entry does (its hash in `catalog.index` changes), named in CHANGELOG.md under *Changed outputs* |
| engines | an engine id removed; an option renamed or removed, or a default changed (a new code id, `.v2`, instead) | a new engine; a new option whose default keeps the old behavior (the same id) |
| the Python API | a public name renamed, removed or given another meaning in `linecaster.data`, `linecaster.formats`, `linecaster.text`, `linecaster.images`, `linecaster.engines.api`, `linecaster.pipelines` (the shapes), `linecaster.runtime.run` (`main`, `recipe`, the helpers the shapes use) or `linecaster.testing` (its checks and markers) | a new name |
| the output files' contents | a change of structure in the files a pipeline writes (ALTO, PAGE-XML, hOCR, Markdown, HTML, JSON) that breaks a reader of the old ones: other elements, attributes or fields | better text; a new optional element or field |
| resuming a run | an unchanged command line gets another fingerprint (`pipeline_sha256`), so a run no longer continues in its folder without `--new-pipeline` | a new operational parameter (left out of the fingerprint) |
| how a run runs | a run that succeeded before now fails or stops | an operational default that leaves the outputs as they were (workers, tasks, threads, windows, timeouts, retries) |
| dependencies and environment | an extra or a dependency removed; a raised minimum (Python, uv, datatrove); another version of a pinned numerical library (torch, ONNX Runtime, a CUDA build), which can change the text a run produces | a relock that moves only other packages; a new extra |
| state shared by runs | a broker layout or an HTTP policy field that older versions, running at the same time, no longer read alike | a new optional field older versions ignore |

Internal modules and names with a leading underscore, log messages, stats, the generated docs, `tests/`, CI, the
docs build and NOTES.md are not part of it: a change there is never more than a patch.

## While the version is 0.x

There is no deprecation period and there are no aliases: a breaking change takes effect in the release that makes
it, and every breaking change is an upgrade note in `CHANGELOG.md` (what changed, who is affected, what to do),
listed first.

## Versions and releases

Versions follow semantic versioning, with the 0.x convention that the minor number does what the major one does
from 1.0 on. What a change bumps follows from the table above:

| Change | While 0.x | From 1.0 |
|---|---|---|
| fixes, performance, corrections of the docs, dependency updates that change no output | patch | patch |
| new blocks, options, presets, recipes, commands or features that keep the old behavior | patch | minor |
| breaking (any surface above; it needs an upgrade note) | minor, collected (0.4.0 → 0.5.0) | major |

A release bumps by its largest change; patches are the rule. Ranges such as the engine packages'
`linecaster>=0.8,<0.10` then hold: every release inside them keeps what worked.

- **Breaking changes are collected, not released one by one.** They are made on a branch and released together as
  one minor, proposed when the branch's work is finished. `main` carries only
  patch-level changes, so a fix can go out as a patch at any time.
- **A minor needs something users must change:** its upgrade notes name it. A release with nothing to change is a
  patch.
- **When:** when the maintainer decides; never one per piece of work or per commit. Finished work is merged into
  `main` and collects in `CHANGELOG.md`'s Unreleased section until then. A release is proposed to the maintainer
  when it is due: the latest release is wrong or incomplete where its users meet it, a user or derivative needs what
  only `main` has, or Unreleased holds a finished piece of work. A commit that changes only the README is no release.
- **How:** the version in `pyproject.toml` and `linecaster.__version__` (`tests/test_version.py` checks they agree),
  `CHANGELOG.md`'s Unreleased section as `## <version> (<date>)`, the scripts relocked, an annotated tag
  `v<version>`, pushed (the docs workflow publishes `<major>.<minor>`). A minor bump while 0.x (a major one from 1.0)
  also widens the engine packages' linecaster range to the next one and bumps each engine package's patch version.
- **Engine packages** version on their own by the same table, applied to their engines (ids, options, defaults).
- **A derivative** pins a linecaster release tag or follows `main` (a recipe script's raw URL), and versions, if at
  all, by its own interface, not by linecaster's numbers.
- **1.0.0** is the maintainer's decision: from then on breaking changes get a deprecation period. No release reaches
  it on its own.

## The catalog and the data formats

The release versions the catalog ([catalog](catalog.md)): an entry is its id, and what it does is the hash of its
functional content, listed in the committed `catalog.index`. A change of what an entry does shows in the index's diff
and is named in CHANGELOG.md under *Changed outputs*, so a user knows what to run again; a run record names every
entry it used with its settings and hash and the linecaster that ran it, which reproduces it. A reference from before
0.10 (`id@N`) resolves to the release's entry, with a warning. Engine and pipeline code ids keep their versions: an
incompatible change of options or slots is a new id, and the old one stays registered.

Data formats keep their own versions, because their files outlive the code: a format's version rises only on an
incompatible change, readers upgrade every older version on load and refuse an unknown one, writers write the
current one, and every file names the linecaster that wrote it.
