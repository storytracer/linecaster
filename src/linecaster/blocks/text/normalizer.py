"""``CharacterNormalizer``: character fidelity *as written* -> *normalized*, on ``Line.normalized`` and
``Paragraph.normalized`` (``normalization.*`` engines; ``normalization.latin-historic.v1`` is the mapping table of
``linecaster.text.variants``). The as-written texts are never touched."""
from __future__ import annotations

from ..base.rule import RuleBlock


class CharacterNormalizer(RuleBlock):
    """The normalized texts of the named transcription's lines and paragraphs by a normalization engine (``preset``:
    e.g. ``latin-historic@1``, or an ``InProcess`` engine spec; ``options`` over it). After a ``Recomposer`` the
    paragraphs are normalized too."""

    name = "character normalizer"
    step = "normalization"
    parts_read = ("text",)
    parts_added = ("normalized",)

    def apply(self, page, t) -> None:
        self.engine(t)
        self.count(t.steps[-1].measurements, ("changed",))
