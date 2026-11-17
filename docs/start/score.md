# Score a run against ground truth

This tutorial measures how well a run read its pages. You need a run (see [Run a recipe](first-run.md)) and
ground truth for the same pages: transcriptions made or checked by people.

## 1. Import the ground truth

Linecaster scores page records against page records, so the ground truth is imported first. Here the ground
truth is a Parquet table with one row per page and the page's ALTO file in the column `alto`:

```bash
uv run pipelines/import_transcriptions.py truth/ --parquet ocr.parquet --data-key alto --importer alto-import
```

The page records are in `truth/pages`. Other importers read PAGE-XML, hOCR, TEI, HTML and plain text;
`linecaster presets --step import` lists them.

## 2. Check it

```bash
linecaster ground-truth check truth/pages
```

This reports what the ground truth holds: how many pages, lines, tables and formulas, in which languages.

## 3. Write a benchmark

A benchmark says how to score: which pages, which comparison and which metrics. This writes one that fits the
ground truth:

```bash
linecaster benchmark init truth/pages benchmark.yaml
```

Open `benchmark.yaml` and read it. It is short, and every choice in it is yours to change.

## 4. Score the run

```bash
linecaster score out/ truth/pages --benchmark benchmark.yaml
```

The results are in `out/scores/`:

| File | What it is |
|---|---|
| `scores.parquet` | the counts for every page |
| `evidence.yaml` | the summary: error rates with their confidence intervals, and exactly how they were measured |

## 5. Compare two runs

Score a second run with the same benchmark. Two evidence records with the same benchmark were measured the same
way, so their numbers can be compared.

## Next

- [Evaluation](../concepts/evaluation.md) explains the parts.
- The [evaluation reference](../reference/evaluation.md) defines every metric.
