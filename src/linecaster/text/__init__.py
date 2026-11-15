"""Text transforms on transcriptions: recomposition of lines into paragraphs (``recomposition``), the typographic
hierarchy (``typography``), the character rules of normalizations (``normalize``) and offsets through a change of
text (``offsets``). Nothing here changes a transcription's text: a text is changed only when it is written, by a
transcription strategy (``linecaster.document.strategy``). Import-light: no datatrove, saturate or engines."""

__all__: list[str] = []
