# Linecaster

### Modular OCR pipelines you can run anywhere

<p align="center">
  <img src="docs/linecaster.png" alt="Line drawing of an Intertype C4 linecaster, a hot-metal typesetting machine" width="353">
</p>
<p align="center"><sub>An Intertype C4 linecaster (1961), after a photograph in the Science Museum Group
Collection, CC BY-NC-SA 4.0. <a href="#-license">Credit</a></sub></p>

Linecaster turns page images into text. You build an OCR pipeline from interchangeable steps (a model that
reads the text, layout, tables, formulas, post-processing) and run it unchanged on a laptop, a GPU server, a
Ray or Slurm cluster or [Hugging Face Jobs][HF Jobs].

- 🧩 **Any step is replaceable.** A vision-language model or a line recognizer reads the text; layout, table
  and formula models and rule-based post-processing are separate steps.
- 🌍 **Any machine.** Only the command line changes, never the pipeline.
- 🎯 **The same result everywhere.** A page's text depends only on that page and the pinned models.
- 🔁 **Built for long runs.** Interrupted runs resume; failed pages are set aside with the reason.

📖 **Docs:** [storytracer.github.io/linecaster](https://storytracer.github.io/linecaster/): the reference, a page
for every block and catalog entry, and [`llms.txt`](https://storytracer.github.io/linecaster/latest/llms.txt) for
coding agents.

## 🚀 Quick start

You need Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13.6 or newer.

```bash
git clone https://github.com/storytracer/linecaster
cd linecaster
uv run launch.py                               # list the recipes and models
uv run pipelines/transcribe_modular.py scans/ out/ --layout pp-doclayoutv3 --lines pp-ocrv6-medium-det \
  --recognition paddlex-ppocrv6-medium         # the modular pipeline, a preset per step
uv run launch.py lightonocr-2-1b scans/ out/   # run a vision-language model (needs vLLM and a GPU)
```

You get one page record per page in `out/pages/`. Add `--files out/files --formats md,alto` for per-page files.

> [!NOTE]
> Every pipeline is a self-contained [uv script][uv scripts] with pinned dependencies and a lock file next to it.
> `uv run` installs what it needs on the first run; models download on first use.

## 🧭 Three ways to transcribe

**1. A recipe**: a tested combination of presets, one per step, with its own edition and evidence. The `squiddle`
recipe reads lines with kraken, which the modular pipeline's script leaves out: it runs with [SquiddleOCR]'s
`squiddle.py`, which adds kraken.

```bash
uv run squiddle.py scans/ out/
```

**2. A vision-language model** reads each page, or each layout region. It runs behind [vLLM] or [SGLang], so it
needs an NVIDIA GPU and the `vllm` command on the PATH.

```bash
uv run launch.py lightonocr-2-1b scans/ out/
uv run pipelines/transcribe_vlm.py scans/ out/ --layout pp-doclayoutv3 --recognition minicpm-ocr-1.0
```

**3. The modular pipeline**: layout, lines and a line recognizer, then post-processing. You choose a preset for
every step; `linecaster models` lists them.

```bash
uv run pipelines/transcribe_modular.py scans/ out/ \
  --layout pp-doclayoutv3 \
  --lines pp-ocrv6-medium-det \
  --recognition paddlex-ppocrv6-medium \
  --typography ratios --recomposition unicode-recomposition --composition docling-composition
```

| Flag | Effect |
|---|---|
| `--layout single-region` | the whole page as one region, no layout model |
| `--tables`, `--formulas` | add table and formula recognition |
| `--typography` | headings and their levels |
| `--recomposition` | running text in paragraphs (without it, the page stays as laid out) |
| `--composition` | the page's document, for Markdown, HTML and JSON |
| `--set recognition.batch_size=4` | change one option of a preset |
| `--files DIR --formats md,alto` | per-page files: ALTO, PAGE-XML, hOCR, text, Markdown, HTML, DocLang, JSON |
| `--dry-run` | print the plan and its graph, run nothing |

Options after a recipe's name override single steps; the run record lists them.

## 📥 Input

| Pages from | Flags |
|---|---|
| a folder of images | `IMAGES` (`--item-from-parent`: each subfolder is an item) |
| a list of images | `IMAGES --paths-file pages.txt` |
| Parquet with an image column | `--parquet PATH` (`--image-key`, `--item-key`, `--sequence-key`) |
| IIIF or METS manifests | `--manifests FOLDER`, `--manifests list.txt`, or `--manifests items.parquet --manifest-key url` |
| an earlier run | `--pages OUT/pages` |

Any fsspec path works: local, `s3://`, `hf://`. Manifests need the `pybookget` extra
([pybookget](https://github.com/storytracer/pybookget)); `--existing-ocr` also keeps the library's own OCR as
`ocr_original`. PDF files are read by the `PdfReader` block (extra `pypdfium2`).

For large collections, fetch the images once, then transcribe, then bind the pages into items:

```bash
uv run pipelines/harvest.py --manifests items.parquet --manifest-key url OUT --rate-limit 5/1
uv run pipelines/transcribe_modular.py --pages OUT/pages OUT2 --layout pp-doclayoutv3 --lines pp-ocrv6-medium-det \
  --recognition paddlex-ppocrv6-medium --item-shards 64
uv run pipelines/bind.py OUT2/pages OUT3 --recipe item-texts
```

## 📦 Output

| Output | For |
|---|---|
| 🗂️ Page records ([JSON Lines], [Parquet]) | later pipelines: every intermediate result |
| 🏛️ [ALTO], [PAGE-XML], [hOCR] | libraries and viewers: every word with its position |
| 📝 Markdown, HTML, DocLang, [Docling] JSON | documents with headings, tables and formulas |
| 📜 `verbatim_txt` per item | the text as printed, for checking against a transcription |
| 📖 `readable_txt`, `readable_md` per item | reading and training: letterforms folded, hyphens joined, paragraphs flowed |

The text as written is always kept; readable text is derived from it. All text is Unicode [NFC]; spelling is never
modernized. Rejected pages go to `rejects/` with the reason. Every run is traced with [OpenTelemetry] into
`OUT/traces/` (nothing is sent anywhere unless you set the `OTEL_*` variables), and `linecaster traces OUT` shows
where the time went.

## 🌍 Run anywhere

| Where | Flags |
|---|---|
| 💻 this machine | none: models load inside the pipeline |
| 🖥️ this machine, with a model server | `--backend served` |
| 🧮 a Ray cluster | `--on ray --tasks 64` |
| ☁️ Hugging Face Jobs | `--on hf-jobs --namespace NS --commit <sha>` |
| 🏛️ a Slurm cluster | from Python, with datatrove's `SlurmPipelineExecutor` ([below](#%EF%B8%8F-your-own-pipeline)) |

On Ray and HF Jobs every task gets one GPU and starts its own model server. A rerun into the same output folder
runs only the tasks that didn't finish.

<details>
<summary><b>A model server that stays up</b></summary>

```bash
P="--layout pp-doclayoutv3 --lines pp-ocrv6-medium-det --recognition paddlex-ppocrv6-medium"
uv run pipelines/transcribe_modular.py serve $P
uv run pipelines/transcribe_modular.py scans/ out/ $P --endpoint http://127.0.0.1:8100/v1
```

A server from another environment works too: `uv run squiddle.py serve` serves the `squiddle` recipe with kraken,
and `uv run launch.py squiddle scans/ out/ --backend served --endpoint http://127.0.0.1:8100/v1` runs the recipe
against it.

For a vision-language model, `--recognition-endpoint` points `transcribe_vlm.py` at a running vLLM or SGLang.
Servers listen on loopback only.

</details>

<details>
<summary><b>Ray</b></summary>

`ray` runs Ray's own command line with the pipeline's packages, so every machine has the same versions:

```bash
uv run pipelines/transcribe_modular.py ray start --head --num-gpus 8
uv run pipelines/transcribe_modular.py scans/ out/ $P --on ray --tasks 64
```

Images, output and the logging folder must be on storage every machine can reach, such as an `s3://` bucket.

Each task reserves `--cpus-per-task` CPUs (default 12), `--mem-per-cpu-gb` GiB of memory per CPU (default 4, so
48 GiB), or `--mem-per-task-gb` GiB whatever its CPUs, and one GPU. Start every worker with at least that much:
`ray start --num-cpus`, `--memory` and `--num-gpus`. Before it submits anything, a launch checks that a live node can
run a task, and stops with what a task needs and what the nodes have. It also logs how many tasks fit at once.
`--no-fit-check` leaves the check out, for a cluster that adds nodes on demand. Each task sizes its thread pools
(OpenMP, BLAS, OpenCV, torch) to its CPUs, not to the machine's.

**On Kubernetes**, one Deployment can run the head and another the workers:

- Start Ray in each pod through the pipeline script (`uv run pipelines/<script>.py ray start …`), so the pods run the
  script's locked packages.
- Give each worker pod the CPUs, memory and GPU a task reserves, plus room for `/dev/shm` (Ray's object store),
  and pass the same amounts to `ray start --num-cpus/--memory/--num-gpus`. A pod with one GPU holds one task.
- With the data on object storage the pods need only ephemeral storage: the environment, the model weights and
  Ray's temporary files.
- Submit the run to the head with `ray job submit`, so it runs inside the cluster and outlives the session that
  submitted it. A driver outside the cluster must reach every node.

</details>

<details>
<summary><b>Hugging Face Jobs</b></summary>

One GPU per Job; each Job installs Linecaster at a pushed commit with the pipeline's pinned dependencies.

```bash
uv run pipelines/transcribe_modular.py s3://bhl-open-data/images hf://buckets/<ns>/<bucket>/<run> $P \
  --paths-file hf://buckets/<ns>/<bucket>/pages.txt --env FSSPEC_S3_ANON=true \
  --on hf-jobs --namespace NS --commit <sha> --tasks 4000 --workers 64
```

`--workers` Jobs run at once. `--flavor l4x4 --gpus 4` runs four tasks per Job. `--dry-run` launches nothing.

</details>

## ✍️ Your own pipeline

A pipeline is a list of blocks; [datatrove] runs it. This is the modular pipeline, cut down:

```python
from datatrove.executor import LocalPipelineExecutor
from linecaster.backends import InProcess as P
from linecaster.blocks.composition import (
    Composer, Recomposer, Typographer)
from linecaster.blocks.layout import LayoutDetector
from linecaster.blocks.lines import (
    LineAssigner, LineDetector)
from linecaster.blocks.readers import ImageFolderReader
from linecaster.blocks.recognition import LineRecognizer
from linecaster.blocks.text import UnicodeNormalizer
from linecaster.blocks.writers import PageFileWriter

pipeline = [
    ImageFolderReader("scans/"),
    LayoutDetector(P("linecaster_paddlex:PaddleLayoutEngine")),
    LineDetector(P("linecaster_paddlex:PaddleLineEngine")),
    LineAssigner(),
    LineRecognizer(
        P("linecaster_paddlex:PaddleRecognitionEngine")),
    UnicodeNormalizer(),
    Typographer("ratios@1"),
    Recomposer("unicode-recomposition@1"),
    Composer("docling-composition@1"),
    PageFileWriter("out/", formats=("md", "alto")),
]
LocalPipelineExecutor(
    pipeline, logging_dir="out/logs").run()
```

The same list runs on a Slurm cluster through [datatrove]'s Slurm executor: one array job, one GPU per task, in an
environment that has the engines (`venv_path`):

```python
from datatrove.executor import SlurmPipelineExecutor

SlurmPipelineExecutor(
    pipeline, tasks=64, time="04:00:00", partition="gpu",
    gpus_per_task=1, venv_path="/path/to/venv",
    logging_dir="out/logs").run()
```

Every block declares what it reads and adds, so a pipeline is checked before it starts: a recognizer without
lines fails at once, with every problem listed. Put the script in `pipelines/` with the `# /// script` block of
`pipelines/transcribe_modular.py` (it brings the engines) and build it with `linecaster.runtime.run.main` to get
the pipelines' command line on every machine. The [pipelines reference](docs/reference/pipelines.md) covers
backends, partial runs (`--until`, `--after`) and the builder.

## 🧩 How it works

1. **One record per page.** Every step reads the page's `Transcription` and adds its part: regions, lines, text,
   tables, a document. Steps share the data model and nothing else.
2. **Contracts.** Each block declares what it reads, adds, replaces or removes; the builder checks the pipeline
   and draws its graph from them.
3. **Backends.** A model step runs `InProcess`, `Served` (a model server reached through [saturate], which keeps
   the GPU busy) or `Chat` (a vision-language model behind an OpenAI-compatible server).
4. **Executors.** [datatrove] splits the pages into tasks, runs them locally, on [Ray], on Slurm or on HF Jobs, and
   resumes where a run stopped.

Models batch only the lines of one page, and model revisions and numerically relevant libraries are pinned, so
a page's output never depends on the machine or on what else runs. Different GPU types can still differ in rare
single characters.

## 🧰 Models and blocks

Every configuration is a **preset** in Linecaster's catalog: an engine, a model at a pinned revision with its
original model card, and settings. Released editions never change. Vision-language models run behind vLLM or
SGLang; the other models run inside the pipeline or behind `linecaster serve`, one package per engine:
`linecaster-kraken` ([kraken]), `linecaster-paddlex` ([PaddleX]) and `linecaster-tesseract` ([Tesseract]).

Every preset and recipe, with its model, settings and evidence: [the catalog](https://storytracer.github.io/linecaster/latest/catalog/).

Every block by family, with its contract, backends and options: [the blocks](https://storytracer.github.io/linecaster/latest/blocks/).

## 📚 Reference

| Page | What it covers |
|---|---|
| [glossary](docs/reference/glossary.md) | every term linecaster uses, one meaning each |
| [architecture](docs/reference/architecture.md) | the packages, how a run fits together, the tests |
| [pipelines](docs/reference/pipelines.md) | blocks and their contracts, the builder, partial runs, failed pages, the run record |
| [data model](docs/reference/data-model.md) | what a page's transcription holds: `Item`, `Page`, `Transcription`, regions, lines, words, text variants |
| [serialization](docs/reference/serialization.md) | how pages are written to and read from ALTO, PAGE-XML and hOCR |
| [catalog](docs/reference/catalog.md) | models, presets, recipes, editions and the evidence behind them |
| [broker](docs/reference/broker.md) | how workers share proxies and other resources across tasks, runs and machines |
| [tracing](docs/reference/tracing.md) | where a run's time went: OpenTelemetry traces per task and for a sample of pages |
| [compatibility](docs/reference/compatibility.md) | what counts as a breaking change and how one is announced |
| [conventions](docs/reference/conventions.md) | the repository's rules: names, spelling, YAML and Markdown, docstrings, logging, errors, secrets |
| [blocks](https://storytracer.github.io/linecaster/latest/blocks/), [catalog](https://storytracer.github.io/linecaster/latest/catalog/) | every block, engine, model, preset and recipe, generated from the code |

## 🏷️ Versions

The current release is `v0.3.2`; [CHANGELOG.md](CHANGELOG.md) lists each release's changes, upgrade notes first.
While the version is 0.x, a breaking release raises the minor version (0.3 → 0.4) and every other release the patch
version ([versions and releases](docs/reference/compatibility.md#versions-and-releases)); there are no deprecation
periods yet. The
[docs site](https://storytracer.github.io/linecaster/) keeps a version per release, `latest` for the newest.
For `main`, run `uv run linecaster docs` and then `uv run --group docs mkdocs serve` in a checkout.

## 📄 License

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
[SquiddleOCR]: https://github.com/storytracer/squiddleocr
[PaddleX]: https://github.com/PaddlePaddle/PaddleX
[Tesseract]: https://github.com/tesseract-ocr/tesseract
[datatrove]: https://github.com/huggingface/datatrove
[saturate]: https://github.com/davanstrien/saturate
[OpenTelemetry]: https://opentelemetry.io/
[Ray]: https://www.ray.io/
[HF Jobs]: https://huggingface.co/docs/huggingface_hub/guides/jobs
[vLLM]: https://github.com/vllm-project/vllm
[SGLang]: https://github.com/sgl-project/sglang
[Docling]: https://github.com/docling-project/docling
[ALTO]: https://www.loc.gov/standards/alto/
[PAGE-XML]: https://github.com/PRImA-Research-Lab/PAGE-XML
[hOCR]: https://kba.github.io/hocr-spec/1.2/
[JSON Lines]: https://jsonlines.org/
[Parquet]: https://parquet.apache.org/
[NFC]: https://unicode.org/reports/tr15/
[uv scripts]: https://docs.astral.sh/uv/guides/scripts/
