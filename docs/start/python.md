# A pipeline in Python

This tutorial builds the pipeline of [Combine models step by step](first-run.md) in Python: a list of components that
you can check, draw, run and change.

## What you need

- Python 3.12 and [uv](https://docs.astral.sh/uv/) 0.13.6 or newer
- a folder of page images, here `scans/`

## 1. Write the script

Save this as `my_pipeline.py`. The comment at the top tells uv which packages the script needs: linecaster and
the engine packages of the models it names.

```python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["linecaster", "linecaster-paddlex", "linecaster-tesseract"]
#
# [tool.uv.sources]
# linecaster = { git = "https://github.com/storytracer/linecaster", branch = "main" }
# linecaster-paddlex = { git = "https://github.com/storytracer/linecaster", branch = "main", subdirectory = "engines/paddlex" }
# linecaster-tesseract = { git = "https://github.com/storytracer/linecaster", branch = "main", subdirectory = "engines/tesseract" }
# ///
from linecaster import Pipeline
from linecaster.components.document import DocumentComposer
from linecaster.components.layout import LayoutDetector
from linecaster.components.lines import LineAssigner, LineDetector
from linecaster.components.readers import ImageFolderReader
from linecaster.components.recognition import LineRecognizer
from linecaster.components.writers import PageFileWriter, PageJsonlWriter

pipeline = Pipeline([
    ImageFolderReader("scans/"),
    LayoutDetector("pp-doclayoutv3"),
    LineDetector("pp-ocrv6-medium-det"),
    LineAssigner(),
    LineRecognizer("paddlex-ppocrv6-medium"),
    DocumentComposer("linked-document"),
    PageJsonlWriter("out/pages"),
    PageFileWriter("out/files", formats=("md", "html")),
])
pipeline.run("out")
```

A **component** does one thing to a page. A model component takes a **preset** by its id, the same ids as on the
command line. `LineAssigner` needs no model: it says which region each line belongs to. `DocumentComposer` builds the page's
document, which the Markdown and HTML files are written from.

## 2. Run it

```bash
uv run my_pipeline.py
```

The page records are in `out/pages/` and the Markdown and HTML files in `out/files/`.

## 3. Swap one component's model

Change one line and run the script again with another output folder:

```python
    LineRecognizer("tesseract-best-latin"),
```

Nothing else changes: the recognizer reads the lines, whoever found them.

## 4. Check a pipeline before it runs

Every component declares what it reads and what it adds. `check()` compares these declarations for the whole
list, and `run()` calls it first. A recognizer without a line detector fails at once:

```python
Pipeline([
    ImageFolderReader("scans/"),
    LineRecognizer("paddlex-ppocrv6-medium"),
    PageJsonlWriter("out/pages"),
]).check()
```

```text
PipelineConfigError: the pipeline cannot run:
- LineRecognizer (recognition (in-process)) reads ocr_new:lines, which no component before it in the pipeline adds
```

`print(pipeline.draw())` prints the pipeline's graph as a Mermaid diagram: which component reads what from which.

## 5. Add components

Components for headings and paragraphs go after the recognizer, before the document:

```python
from linecaster.components.hierarchy import HierarchyDetector
from linecaster.components.paragraphs import ParagraphBuilder

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
    PageFileWriter("out/files", formats=("md", "html")),
])
```

## 6. Keep a pipeline as data

`pipeline.to_dict()` gives the pipeline as plain data, and `Pipeline.from_dict()` builds it again. The data names
every component with its options and every preset with its hash.

## Next

- [Components and pipelines](../concepts/pipelines.md) explains components, contracts and backends.
- The [components reference](../components/README.md) has a page for each component.
- [Running at scale](../reference/running.md): the same pipeline on a cluster.
