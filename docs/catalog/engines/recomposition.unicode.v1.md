# recomposition.unicode.v1

*Engine · recomposition · package `linecaster`*

squiddleocr's recomposition (`linecaster.text.recomposition`): the rows of each text region joined into
paragraphs, the typesetter's division marks removed, from geometry and Unicode's character properties (line,
word and sentence breaks), never from a language name; the document's own words decide the one ambiguous case
(a hyphen that may belong to the word). The pages of an item share that lexicon, in order. Covers every
script whose text runs in horizontal lines.

Makes the paragraphs of each region; the decisions, the continuation across regions and pages and the
text-only fallback come with the Recomposer. Options other than the defaults are refused until the rules take
them as parameters.

|  |  |
|---|---|
| Class | `linecaster.engines:UnicodeRecompositionEngine` |
| Source | [recomposition.py](../../../src/linecaster/engines/recomposition.py) |
| Reads | items |
| Produces | paragraphs |
| Scripts | all |
| Runs | in the pipeline's process |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `rtl` | `bool` | `False` | the writing direction is right to left (start and end margins) |
| `convention_marks` | `str` | `'¬'` | characters a transcription convention writes for a line-end hyphen, besides Unicode's hyphens |
