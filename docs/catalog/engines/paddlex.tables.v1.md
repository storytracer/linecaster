# paddlex.tables.v1

*Engine · tables · package `linecaster-paddlex`*

linecaster engine for the tables step: the cell structure of every `table` region, with the
region's recognized lines placed into the cells (needs the recognition step first). The result goes
into `region.extra["table"]`: `num_rows`, `num_cols`, `html` and `cells` (text, row, col,
row_span, col_span, bbox, header).

The pipeline's models: the structure model (`STRUCTURE`, for wired and wireless tables) from `weights`
(a catalog pin) or the catalog's newest pin; the classifier and the two cell detectors (`SUBMODELS`) at
`submodel_weights` (catalog pins by PaddleX name, from a preset's `submodels`), else
`submodel_revisions` (each a pin of its model document; edition 1 of `slanet-plus`), else their newest
pins.

|  |  |
|---|---|
| Class | `linecaster_paddlex:PaddleTableEngine` |
| Source | [tables.py](../../../engines/paddlex/src/linecaster_paddlex/tables.py) |
| Reads | regions |
| Produces | tables, html |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `device` | `str` | `'auto'` | auto, cpu, cuda, tensorrt or coreml (ONNX Runtime providers) |
| `crop_pad` | `int` | `8` | pixels the table region's crop is grown by (with the exact layout box the models can flip to a worse cell set; stable from 8 px) |
| `e2e` | `bool` | `True` | structure and cell boxes from SLANet_plus's own prediction for both table classes (False: the cell detectors, PP-StructureV3's route) |
| `name` | `str` | `'table_recognition_v2/SLANet_plus'` | the name recorded in StepInfo |
| `submodel_revisions` | `dict[str, str] \| None` | `None` | PaddleX model name -> Hugging Face commit of its ONNX package, for the table classifier and the cell detectors; each must be a pin in the catalog (None: the newest pins) |

## Presets

- [`slanet-plus`](../presets/tables/slanet-plus.md)
