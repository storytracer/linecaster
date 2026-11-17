# Text and normalization

## The text as read

A page record stores each line's text exactly as the model or the source gave it. Linecaster does not even apply
Unicode normalization to it. This stored text is the **reading**.

The reason is trust. A rule that looks safe can be wrong often. A rule that joins words divided at a line end,
for example, also joins compounds that have a hyphen of their own. A silent change of this kind is an error that
nobody sees.

## Changes are named

Every change of a text has a name and is a catalog entry, a **normalization**:

| Normalization | What it does |
|---|---|
| `nfc` | Unicode NFC |
| `long-s` | writes the long s (ſ) as s |
| `ligatures` | writes ligatures as their letters |
| `flow` | joins the lines of a paragraph into running text |
| `unicode-marks` | removes a hyphen where a word was divided at a line end |

## Strategies

A **strategy** is an ordered list of normalizations. You name one when a text is written:

```bash
--text literal:txt                    # the text as read
--text latin-historic+flow:md         # a catalog strategy, then flow, as Markdown
```

`literal` is the strategy that changes nothing. There is no default strategy that changes text: if you name
none, you get the text as read.

## Scoring uses the same idea

When a run is compared with ground truth, both sides go through the same strategy first, called a **lane**. The
lane `diplomatic` compares the texts almost as they are; `reading` ignores differences a reader would not notice.

## Reference

The [catalog reference](../reference/catalog.md) lists the normalizations and strategies.
