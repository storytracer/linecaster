# Components and pipelines

## Components

A component does one thing to a page: it finds the lines, reads them, or writes a file. Technically it is a
datatrove `PipelineStep`. Components are named after what they do.

| Step | Components | What they add |
|---|---|---|
| reading input | `ImageFolderReader`, `ImageParquetReader`, `ManifestReader`, `PdfReader`, `PageRecordReader` | the page and its image |
| `layout` | `LayoutDetector` | regions and their reading order |
| `lines` | `LineDetector`, `LineAssigner` | lines, and which region each belongs to |
| `recognition` | `LineRecognizer`, `PageRecognizer`, `RegionRecognizer` | the text |
| `tables`, `formulas` | `TableRecognizer`, `FormulaRecognizer` | table cells, LaTeX |
| `hierarchy` | `HierarchyDetector` | heading levels |
| `paragraphs` | `ParagraphBuilder` | paragraphs |
| `document` | `DocumentComposer` | the document |
| writing output | `PageJsonlWriter`, `PageParquetWriter`, `PageFileWriter`, `ItemTextWriter`, ... | files |

The [components reference](../components/README.md) has a page for each.

## Contracts

Every component declares a **contract**: which parts of the page record it reads and which it adds. A
`LineRecognizer` reads the image and the lines, and adds the text.

Before a run starts, linecaster checks the contracts of the whole pipeline. If a component reads something that no
earlier component adds, the run does not start and the message says what is missing.

## Writing a pipeline

A `Pipeline` is a list of components:

```python
from linecaster import Pipeline
from linecaster.components.layout import LayoutDetector
from linecaster.components.lines import LineAssigner, LineDetector
from linecaster.components.readers import ImageFolderReader
from linecaster.components.recognition import LineRecognizer
from linecaster.components.writers import PageJsonlWriter

pipeline = Pipeline([
    ImageFolderReader("scans/"),
    LayoutDetector("pp-doclayoutv3"),
    LineDetector("pp-ocrv6-medium-det"),
    LineAssigner(),
    LineRecognizer("kraken-ppocrv6-medium"),
    PageJsonlWriter("out/pages"),
])
pipeline.check()        # the contracts, before anything runs
pipeline.run("out")     # on this machine
```

A model component takes a preset by its id. `check()` returns a plan of stages, and each stage is a list that any
datatrove executor runs: `pipeline.run()` uses the local one. `pipeline.to_dict()` gives the pipeline as plain
data, and `Pipeline.from_dict()` builds it again.

## Pipeline templates and scripts

Most people do not write the list themselves. A **pipeline template** builds a common kind of pipeline from
command-line options, and a **pipeline script** in `pipelines/` runs one template in its own environment:

| Script | Builds |
|---|---|
| `transcribe_modular.py` | layout, lines, a line recognizer, then hierarchy, paragraphs and the document |
| `transcribe_vlm.py` | a vision-language model per page, or per layout region |
| `transcribe_page.py` | a page engine per page |
| `harvest.py` | downloads page images from manifests |
| `bind.py` | item texts and item documents from page records |
| `convert.py` | converts page images |
| `import_transcriptions.py` | reads transcriptions in any format into page records |
| `score.py` | scores a run against a ground truth |

A template has a **slot** for each step, and you fill a slot with a preset: `--layout pp-doclayoutv3`. No slot has
a default. A **recipe** fills all slots at once.

## Where a model runs

A model component runs its engine in one of three places, its **backend**:

- in the pipeline's own process,
- behind `linecaster serve`, a server that hosts engines,
- behind an OpenAI-compatible server such as vLLM, for vision-language models.

The result is the same in all three: a request carries one page, and a page's result depends only on that page.

## Reference

[Pipelines](../reference/pipelines.md) has the details: contracts, checks, failures, the run record, samples.
