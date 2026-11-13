"""Content roles and rendering policies: what a region is, and where a rendering puts it.

A region's **content role** is a ``role`` classification (``ROLES``: PAGE-XML's region types, with docling-core's
labels where PAGE has no word). A **rendering policy** (``RenderingPolicy``, a catalog entry ``policy``) decides
which annotations go into which **layer** of a rendering (docling-core's content layers, ``metadata`` or ``none``)
and whose annotations count where several annotators gave one.

Engines and readers that speak Docling labels (a layout model's label map, a delivered DoclingDocument) classify
through ``role_of_label``; renderers that write Docling labels read them back through ``docling_label``. A label
that is neither a role nor a Docling label is kept as it is, as its own role.
"""
from __future__ import annotations

from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

#: the layers a rendering puts content in: docling-core's ``ContentLayer`` values, ``metadata`` and ``none``
LAYERS = ("body", "furniture", "background", "invisible", "notes", "metadata", "none")

#: content role -> (PAGE-XML region type, docling-core label, default layer)
ROLES: dict[str, tuple[str, str, str]] = {
    "paragraph": ("paragraph", "text", "body"),
    "heading": ("heading", "section_header", "body"),
    "title": ("heading", "title", "body"),
    "caption": ("caption", "caption", "body"),
    "list_item": ("paragraph", "list_item", "body"),
    "list_label": ("list-label", "list_item", "body"),
    "toc_entry": ("TOC-entry", "document_index", "body"),
    "footnote": ("footnote", "footnote", "body"),
    "footnote_continued": ("footnote-continued", "footnote", "body"),
    "endnote": ("endnote", "footnote", "body"),
    "marginalia": ("marginalia", "text", "body"),
    "drop_capital": ("drop-capital", "text", "body"),
    "credit": ("credit", "text", "body"),
    "floating": ("floating", "text", "body"),
    "reference": ("paragraph", "reference", "body"),
    "code": ("other", "code", "body"),
    "table": ("TableRegion", "table", "body"),
    "formula": ("MathsRegion", "formula", "body"),
    "chemistry": ("ChemRegion", "formula", "body"),
    "music": ("MusicRegion", "picture", "body"),
    "picture": ("ImageRegion", "picture", "body"),
    "chart": ("ChartRegion", "chart", "body"),
    "map": ("MapRegion", "picture", "body"),
    "advert": ("AdvertRegion", "picture", "body"),
    "form": ("other", "form", "body"),
    "key_value": ("other", "key_value_region", "body"),
    "header": ("header", "page_header", "furniture"),
    "footer": ("footer", "page_footer", "furniture"),
    "page_number": ("page-number", "page_header", "furniture"),
    "catch_word": ("catch-word", "page_footer", "furniture"),
    "signature_mark": ("signature-mark", "page_footer", "furniture"),
    "separator": ("SeparatorRegion", "picture", "none"),
    "noise": ("NoiseRegion", "picture", "none"),
    "other": ("other", "text", "body"),
}

#: a Docling label -> the content role it is read as (labels not listed: their own role)
DOCLING_ROLES: dict[str, str] = {
    "text": "paragraph", "paragraph": "paragraph", "section_header": "heading", "title": "title",
    "caption": "caption", "list_item": "list_item", "document_index": "toc_entry", "footnote": "footnote",
    "reference": "reference", "code": "code", "table": "table", "formula": "formula", "picture": "picture",
    "chart": "chart", "form": "form", "key_value_region": "key_value", "page_header": "header",
    "page_footer": "footer", "handwritten_text": "paragraph",
}

#: roles whose Docling label depends on where the zone is: page_header in the top half of the page, else page_footer
_PLACED = frozenset({"page_number"})


def role_of_label(label: str) -> tuple[str, str | None]:
    """The content role a label is read as, and the production it implies (``handwritten_text``: handwritten):
    a role as itself, a Docling label by ``DOCLING_ROLES``, anything else as its own role."""
    if label in ROLES:
        return label, None
    return DOCLING_ROLES.get(label, label), ("handwritten" if label == "handwritten_text" else None)


def classify_label(t, annotator: int, target: str, label: str, **fields) -> str:
    """Adds the ``role`` classification (and a ``production`` one where the label implies it) of ``label`` for
    ``target``; returns the role."""
    role, production = role_of_label(label)
    t.classify(annotator, target, "role", role, **fields)
    if production is not None:
        t.classify(annotator, target, "production", production)
    return role


def docling_label(t, target: str, role: str | None = None) -> str:
    """The Docling label of ``target`` (a region id) from its content role (``role``, or its resolved one): a
    page number is ``page_header`` in the top half of the page (or without a box), else ``page_footer``; a role
    without a Docling label of its own is written as it is."""
    role = role if role is not None else (t.role(target) or "paragraph")
    if role in _PLACED:
        r = t.region(target)
        height = t.source.image_height
        if r is not None and r.box is not None and height:
            return "page_header" if r.box[1] + r.box[3] / 2 < height / 2 else "page_footer"
        return "page_header"
    return ROLES[role][1] if role in ROLES else role


def default_layer(role: str | None) -> str:
    return ROLES[role][2] if role in ROLES else "body"


class RenderingRule(BaseModel):
    """One rule of a policy: what it matches (``None``: anything) and the layer it puts it in."""

    model_config = ConfigDict(extra="forbid")

    role: str | None = Field(None, description="the content role it matches")
    production: str | None = Field(None, description="the production it matches")
    status: str | None = Field(None, description="the status it matches")
    motivation: str | None = Field(None, description="the motivation it matches: transcribing, describing, ...")
    to: Literal["body", "furniture", "background", "invisible", "notes", "metadata", "none"] = Field(
        description="the layer")

    def matches(self, role, production, status, motivation) -> bool:
        return all(want is None or want == have for want, have in ((self.role, role), (self.production, production),
                                                                  (self.status, status),
                                                                  (self.motivation, motivation)))


class RenderingPolicy(BaseModel):
    """Which annotations go into which layer of a rendering, and whose annotations count where several annotators
    gave one. Rules are tried in order; the first that matches wins; without a match, the role's default layer."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="the policy's name")
    edition: int = Field(1, description="its edition")
    rules: list[RenderingRule] = Field(default_factory=list, description="the rules, first match wins")
    precedence: dict[str, list[str]] = Field(
        default_factory=dict, description="per scheme (role, heading_level, ...) or `order`: the steps or annotator "
                                          "names whose annotations count first; the latest annotator otherwise")
    edits: dict[str, list[str]] = Field(default_factory=dict,
                                        description="per text variant: the edit kinds it applies")

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.edition}"

    def layer(self, role: str | None, production: str | None = None, status: str | None = None,
              motivation: str = "transcribing") -> str:
        for rule in self.rules:
            if rule.matches(role, production, status, motivation):
                return rule.to
        if motivation == "describing":
            return "metadata"
        return default_layer(role)

    def layer_of(self, t, target: str) -> str:
        """The layer of an annotation set's ``target`` (a region): its role, production and status, resolved by
        the policy's precedence."""
        prec = self.precedence
        return self.layer(t.classification(target, "role", prec.get("role")),
                          t.classification(target, "production", prec.get("production"))
                          or t.classification("", "production", prec.get("production")),
                          t.classification(target, "status", prec.get("status")))

    def kinds(self, variant: str, default: Iterable[str] = ("nfc",)) -> tuple[str, ...]:
        return tuple(self.edits.get(variant, default))


#: the default policy (the catalog's ``page-layers@1``): every role in its default layer, what is suppressed,
#: duplicate or removed nowhere, descriptions in the metadata
DEFAULT_POLICY = RenderingPolicy(
    id="page-layers", edition=1,
    rules=[RenderingRule(status=s, to="none") for s in ("suppressed", "duplicate", "removed")],
    edits={"verbatim_txt": ["nfc"], "readable_txt": ["nfc", "joined", "normalized"],
           "readable_md": ["nfc", "joined", "normalized"]})


def policy_dict(p: RenderingPolicy) -> dict[str, Any]:
    return p.model_dump(mode="json", exclude_defaults=True)
