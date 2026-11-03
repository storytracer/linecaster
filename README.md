# linecaster

An open, modular text-recognition suite for print and handwriting. It combines layout, line, text,
table and formula recognisers with post-processing such as dehyphenation and reflow into
reproducible [datatrove](https://github.com/huggingface/datatrove) pipelines that turn page images
into text: the text as written, readable variants next to it, and ALTO, PAGE-XML and hOCR on
request. It runs anywhere datatrove runs, from a single machine to Slurm, Ray or Hugging Face Jobs.

Status: early development; nothing here is stable yet.

## How it fits together

- **Blocks** are datatrove pipeline steps: readers, model steps (layout, lines, recognition, ...),
  CPU transforms, filters and writers. A chain (say, a layout model, a line detector and a
  recogniser) is a datatrove pipeline of blocks, so any segmenter can be combined with any recogniser.
- **Models run behind servers.** `linecaster serve` hosts engine models (each in its own environment
  with its own heavy dependencies) over HTTP; the model blocks reach them through
  [saturate](https://github.com/davanstrien/saturate), which keeps the right number of pages in flight.
  The same models also run in-process, for checking and small jobs.
- **One page, one row**: a `Page` with its image and named transcriptions (`Transcription`: regions,
  lines, words and a DoclingDocument), exported to ALTO, PAGE-XML, hOCR and text.

```
envs/kraken-paddlex/.venv/bin/python -m linecaster.cli serve --config examples/squiddle_models.json
.venv/bin/python examples/squiddle_chain.py IMAGES OUT --backend served
```

See `NOTES.md` for measurements and `specs/` for the design decisions.

## Licence

Apache-2.0, see [LICENSE](LICENSE).
