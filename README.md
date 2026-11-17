# Linecaster

### Modular OCR pipelines you can run anywhere

<p align="center">
  <img src="docs/linecaster.png" alt="Line drawing of an Intertype C4 linecaster, a hot-metal typesetting machine" width="353">
</p>
<p align="center"><sub>An Intertype C4 linecaster (1961), after a photograph in the Science Museum Group
Collection, CC BY-NC-SA 4.0. <a href="#license">Credit</a></sub></p>

Linecaster turns page images into text. A pipeline is a chain of steps, and for every step you pick a model:

```mermaid
flowchart LR
    I[page images] --> L[layout] --> D[lines] --> R[recognition] --> P[headings and paragraphs] --> O[page records and files]
```

Any model can be swapped for another without touching the rest. The same pipeline runs on a laptop, a GPU
server, a Ray or Slurm cluster or [Hugging Face Jobs][HF Jobs].

- **Combine models freely.** Layout, line, text, table and formula models from [PaddleX], [kraken] and
  [Tesseract], and vision-language models that read a whole page, all behind the same few options.
- **Run anywhere.** Only the command line changes, never the pipeline. A page's text depends only on that page
  and on models pinned to an exact revision.
- **Built for long runs.** An interrupted run resumes. A page that fails is set aside with the reason.
- **Nothing is lost or changed silently.** Each page has one record that holds what every step found and which
  model found it. The text is stored exactly as read.
- **Standards in and out.** Folders, buckets, Parquet, PDF, IIIF and METS manifests in; [ALTO], [PAGE-XML],
  [hOCR], Markdown, HTML, [Parquet] and [JSON Lines] out.
- **Measurable.** Linecaster reads ground truth in the same formats and scores a run against it.

**Documentation:** [storytracer.github.io/linecaster](https://storytracer.github.io/linecaster/)

## Quick start

You need Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13.6 or newer. An NVIDIA GPU is recommended.

```bash
git clone https://github.com/storytracer/linecaster
cd linecaster
uv run pipelines/transcribe_modular.py scans/ out/ \
  --layout pp-doclayoutv3 \
  --lines pp-ocrv6-medium-det \
  --recognition paddlex-ppocrv6-medium \
  --files out/files --formats txt,alto
```

This reads the images in `scans/` and writes:

| In `out/` | What it is |
|---|---|
| `pages/` | one page record per page: everything that was found, with who found it |
| `files/` | a text file and an ALTO file per page |
| `rejects/` | pages that failed, each with the reason |
| `run.yaml` | the run record: what ran, with which models and versions |

> [!NOTE]
> There is nothing to install. Every pipeline is a [uv script][uv scripts] with pinned dependencies, which
> `uv run` installs on the first run. Models download on first use.

## Combine models

Each option names a **preset**: a model at a pinned revision with its settings. `linecaster presets` lists them
by step:

```bash
uv run linecaster presets --step recognition
```

To swap a model, change one option. This run keeps the layout and the lines and reads the text with Tesseract:

```bash
uv run pipelines/transcribe_modular.py scans/ out/ \
  --layout pp-doclayoutv3 \
  --lines pp-ocrv6-medium-det \
  --recognition tesseract-best-latin
```

More steps are more options:

| Option | Step |
|---|---|
| `--layout` | the regions of a page and their order (`single-region`: the whole page, no layout model) |
| `--lines` | the lines |
| `--recognition` | the text of each line |
| `--tables` | table cells |
| `--formulas` | formulas as LaTeX (its model needs torch: run it in a script that installs torch, as a recipe's does) |
| `--hierarchy` | headings and their levels |
| `--paragraphs` | lines joined into paragraphs |
| `--document` | the page as a document, for Markdown, HTML and JSON |

No step has a default, so a run always names what it ran. `--set recognition.batch_size=4` changes one setting
of a preset, `--dry-run` prints the plan and runs nothing, and `--help` lists everything else.

Tutorial: [Your first pipeline](docs/start/first-run.md).

## The same in Python

A `Pipeline` is a list of components, one for each thing that happens to a page. Save this as a script and run
it with `uv run`:

```python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["linecaster", "linecaster-paddlex"]
#
# [tool.uv.sources]
# linecaster = { git = "https://github.com/storytracer/linecaster", branch = "main" }
# linecaster-paddlex = { git = "https://github.com/storytracer/linecaster", branch = "main", subdirectory = "engines/paddlex" }
# ///
from linecaster import Pipeline
from linecaster.components.document import DocumentComposer
from linecaster.components.hierarchy import HierarchyDetector
from linecaster.components.layout import LayoutDetector
from linecaster.components.lines import LineAssigner, LineDetector
from linecaster.components.paragraphs import ParagraphBuilder
from linecaster.components.readers import ImageFolderReader
from linecaster.components.recognition import LineRecognizer
from linecaster.components.writers import PageFileWriter, PageJsonlWriter

pipeline = Pipeline([
    ImageFolderReader("scans/"),
    LayoutDetector("pp-doclayoutv3"),
    LineDetector("pp-ocrv6-medium-det"),
    LineAssigner(),
    LineRecognizer("paddlex-ppocrv6-medium"),
    HierarchyDetector("ratios"),
    ParagraphBuilder("unicode-paragraphs"),
    DocumentComposer("linked-document"),
    PageJsonlWriter("out/pages"),
    PageFileWriter("out/files", formats=("md", "alto")),
])
pipeline.run("out")
```

Every component declares what it reads and what it adds. `run` checks these declarations first, so a pipeline
that cannot work stops before it starts: a recognizer without a line detector fails at once, with the reason.
`pipeline.draw()` gives the pipeline's graph, and `pipeline.to_dict()` the pipeline as plain data.

Tutorial: [A pipeline in Python](docs/start/python.md).

## Vision-language models

A vision-language model reads a whole page in one request, so its pipeline has one step to fill. The model runs
behind [vLLM] or [SGLang], which needs an NVIDIA GPU and the `vllm` command on the `PATH`:

```bash
uv run pipelines/transcribe_vlm.py scans/ out/ --recognition lightonocr-2-1b
```

With a layout preset, the model reads one region at a time:

```bash
uv run pipelines/transcribe_vlm.py scans/ out/ --layout pp-doclayoutv3 --recognition minicpm-ocr-1.0
```

Tutorial: [Run a vision-language model](docs/start/vlm.md).

## Recipes

A **recipe** is a tested combination kept under a name: one preset for each step, and the texts to write. A
recipe has a script of its own with exactly the engines it needs, and `launch.py` runs it by name:

```bash
uv run launch.py                          # list the recipes
uv run launch.py squiddle scans/ out/     # run one
```

Options after the name replace single steps, and the run record lists what was changed. A recipe's script also
runs from its URL, without a checkout:

```bash
uv run https://raw.githubusercontent.com/storytracer/linecaster/main/recipes/squiddle.py scans/ out/
```

## Input and output

| Pages from | Options |
|---|---|
| a folder of images | `IMAGES` (with `--item-from-parent`, each subfolder is an item) |
| a list of images | `IMAGES --paths-file pages.txt` |
| Parquet with an image column | `--parquet PATH` |
| IIIF or METS manifests | `--manifests FOLDER`, or a list or a Parquet table of their URLs |
| an earlier run | `--pages OUT/pages` |

Paths can be local or remote: `s3://`, `hf://`, `http(s)://` and every other [fsspec] protocol.

| Output | Option |
|---|---|
| page records, as JSON Lines or Parquet | always, in `OUT/pages/` |
| ALTO, PAGE-XML and hOCR, with every word's position | `--files DIR --formats alto,page,hocr` |
| plain text, Markdown, HTML and JSON per page | `--files DIR --formats txt,md,html,json` |
| one text per book or issue | `--item-texts DIR --text literal:txt`, with `--document` |

The stored text is exactly what the model read. Joining divided words, folding historic letterforms and similar
changes are made only in a text you ask for, by rules you name: `--text latin-historic+flow:md`.
[Text and normalization](docs/concepts/text.md) explains why.

## Run anywhere

| Where | Options |
|---|---|
| this machine | none: the models load inside the pipeline |
| this machine, with a model server | `--backend served` |
| a Ray cluster | `--on ray --tasks 64` |
| Hugging Face Jobs | `--on hf-jobs --namespace NS --commit <sha>` |
| a Slurm cluster | from Python, with [datatrove]'s Slurm executor |

Linecaster builds on [datatrove], which divides the pages into tasks and resumes a run where it stopped.
[Running at scale](docs/reference/running.md) has the setup for each of these, and for collections that are
fetched first and transcribed later.

## Score a run

Ground truth is read into the same page records as a run's output, so the two can be compared:

```bash
uv run pipelines/import_transcriptions.py truth/ --parquet ocr.parquet --data-key alto --importer alto-import
uv run linecaster benchmark init truth/pages benchmark.yaml
uv run linecaster score out/ truth/pages --benchmark benchmark.yaml
```

The result is an evidence record: error rates with their confidence intervals, and exactly how they were
measured. Tutorial: [Score a run against ground truth](docs/start/score.md).

## How it works

| Term | Meaning |
|---|---|
| component | does one thing to a page: finds the lines, reads them, writes a file |
| step | one kind of work: `layout`, `lines`, `recognition`, `tables`, `formulas`, `hierarchy`, `paragraphs`, `document` |
| engine | the code that runs a model: one package per OCR library (`linecaster-paddlex`, `linecaster-kraken`, `linecaster-tesseract`, ...) |
| preset | an engine, a model at a pinned revision and settings, under one name; what you pick for a step |
| recipe | a tested set of presets, one for each step |
| page record | everything the components found on one page, each finding with the model that made it |
| run record | what a run ran: every preset with its hash, and the versions |

A component adds to the page record and never overwrites what is there. Files and texts are written from the
record, so one run can serve ALTO to a library and Markdown to a reader. The
[overview](docs/concepts/overview.md) explains these ideas in a few minutes.

## Documentation

| | |
|---|---|
| Get started | [Your first pipeline](docs/start/first-run.md), [A pipeline in Python](docs/start/python.md), [Run a vision-language model](docs/start/vlm.md), [Score a run](docs/start/score.md) |
| Concepts | [Overview](docs/concepts/overview.md), [components and pipelines](docs/concepts/pipelines.md), [models, engines and presets](docs/concepts/models.md), [page records](docs/concepts/page-records.md), [text and normalization](docs/concepts/text.md), [evaluation](docs/concepts/evaluation.md) |
| Look up | [every component](https://storytracer.github.io/linecaster/latest/components/), [every preset, model and recipe](https://storytracer.github.io/linecaster/latest/catalog/), the [glossary](docs/reference/glossary.md) |
| Reference | [architecture](docs/reference/architecture.md), [pipelines](docs/reference/pipelines.md), [data model](docs/reference/data-model.md), [serialization](docs/reference/serialization.md), [catalog files](docs/reference/catalog.md), [evaluation](docs/reference/evaluation.md) |
| Operations | [running at scale](docs/reference/running.md), [fetching over HTTP](docs/reference/http.md), [broker](docs/reference/broker.md), [tracing](docs/reference/tracing.md) |
| Contributing | [conventions](docs/reference/conventions.md), [compatibility and releases](docs/reference/compatibility.md) |

For coding agents, the site has an [`llms.txt`](https://storytracer.github.io/linecaster/latest/llms.txt).

## Versions

The current release is `v0.13.1`. [CHANGELOG.md](CHANGELOG.md) lists each release's changes, upgrade notes
first. While the version is 0.x, a release that breaks something raises the minor version and names what to
change ([versions and releases](docs/reference/compatibility.md#versions-and-releases)).

## License

The code is Apache-2.0, see [LICENSE](LICENSE).

<details>
<summary><b>Image credit</b></summary>

The drawing of the linecaster is by Sebastian Majstorovic, made with Adobe Illustrator and Google Gemini. It is
based on a photograph of the
[Intertype C4 Linecaster](https://collection.sciencemuseumgroup.org.uk/objects/co8407592/intertype-c4-linecaster)
(Intertype Ltd, Slough, 1961; object Y1990.104.12, gift of M.H. Whittaker & Son) in the Science Museum Group
Collection. Photograph © The Board of Trustees of the Science Museum, released under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), redrawn as a black-and-white line drawing.

The drawing is an adaptation of that photograph and is licensed under the same terms,
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). It may not be used for commercial
purposes. The Apache-2.0 license of the code does not apply to it. The same credit is in
[docs/LICENSE-linecaster-image.md](docs/LICENSE-linecaster-image.md).

</details>

<!-- links -->
[kraken]: https://github.com/mittagessen/kraken
[PaddleX]: https://github.com/PaddlePaddle/PaddleX
[Tesseract]: https://github.com/tesseract-ocr/tesseract
[datatrove]: https://github.com/huggingface/datatrove
[fsspec]: https://filesystem-spec.readthedocs.io/
[HF Jobs]: https://huggingface.co/docs/huggingface_hub/guides/jobs
[vLLM]: https://github.com/vllm-project/vllm
[SGLang]: https://github.com/sgl-project/sglang
[ALTO]: https://www.loc.gov/standards/alto/
[PAGE-XML]: https://github.com/PRImA-Research-Lab/PAGE-XML
[hOCR]: https://kba.github.io/hocr-spec/1.2/
[JSON Lines]: https://jsonlines.org/
[Parquet]: https://parquet.apache.org/
[uv scripts]: https://docs.astral.sh/uv/guides/scripts/
