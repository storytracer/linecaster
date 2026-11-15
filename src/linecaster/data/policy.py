"""Content roles and rendering policies: what a region is, and where a rendering puts it.

A region's **content role** is a ``role`` classification (``ROLES``: PAGE-XML's region types, with names of
linecaster's own where PAGE has no word). A **rendering policy** (``RenderingPolicy``, a catalog entry ``policy``)
decides which annotations go into which **layer** of a rendering (``LAYERS``) and whose annotations count where several
annotators gave one.

A **region label** is the coarser word layout models and page files use for a region (``text``, ``title``,
``section_header``, ``caption``, ``footnote``, ``list_item``, ``page_header``, ``page_footer``, ``table``,
``picture``, ...: ``ROLES``' second column). Engines and readers that speak region labels (a layout preset's label
map, a page file's region types) classify through ``role_of_label``; writers that need one read it back through
``region_label``. A label that is neither a role nor a region label is kept as it is, as its own role.
"""
from __future__ import annotations

from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

#: the layers a rendering puts content in: the body, the page's furniture (running heads and feet), background,
#: invisible text, notes; ``metadata`` and ``none`` are never rendered
LAYERS = ("body", "furniture", "background", "invisible", "notes", "metadata", "none")

#: content role -> (PAGE-XML region type, region label, default layer)
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

#: a region label -> the content role it is read as (labels not listed: their own role)
LABEL_ROLES: dict[str, str] = {
    "text": "paragraph", "paragraph": "paragraph", "section_header": "heading", "title": "title",
    "caption": "caption", "list_item": "list_item", "document_index": "toc_entry", "footnote": "footnote",
    "reference": "reference", "code": "code", "table": "table", "formula": "formula", "picture": "picture",
    "chart": "chart", "form": "form", "key_value_region": "key_value", "page_header": "header",
    "page_footer": "footer", "handwritten_text": "paragraph",
}

#: roles whose region label depends on where the zone is: page_header when the box's centre lies in the top
#: ``HEADER_ZONE`` of the page (as PP-DocLayout's ``number`` is placed), else page_footer
_PLACED = frozenset({"page_number"})
HEADER_ZONE = 0.15


def role_of_label(label: str) -> tuple[str, str | None]:
    """The content role a label is read as, and the production it implies (``handwritten_text``: handwritten):
    a role as itself, a region label by ``LABEL_ROLES``, anything else as its own role."""
    if label in ROLES:
        return label, None
    return LABEL_ROLES.get(label, label), ("handwritten" if label == "handwritten_text" else None)


def classify_label(t, annotator: int, target: str, label: str, **fields) -> str:
    """Adds the ``role`` classification (and a ``production`` one where the label implies it) of ``label`` for
    ``target``; returns the role."""
    role, production = role_of_label(label)
    t.classify(annotator, target, "role", role, **fields)
    if production is not None:
        t.classify(annotator, target, "production", production)
    return role


def region_label(t, target: str, role: str | None = None) -> str:
    """The region label of ``target`` (a region id) from its content role (``role``, or its resolved one): a
    page number is ``page_header`` when its centre lies in the top ``HEADER_ZONE`` of the page (or without a box),
    else ``page_footer``; a role without a region label of its own is written as it is."""
    role = role if role is not None else (t.role(target) or "paragraph")
    if role in _PLACED:
        r = t.region(target)
        height = t.source.image_height
        if r is not None and r.box is not None and height:
            return "page_header" if r.box[1] + r.box[3] / 2 < HEADER_ZONE * height else "page_footer"
        return "page_header"
    return ROLES[role][1] if role in ROLES else role


#: the region labels whose regions hold running text (the others: tables, pictures, charts, forms), each to the label
#: its text takes (``paragraph`` is ``text``)
TEXT_LABELS = {
    "text": "text", "paragraph": "text", "title": "title", "section_header": "section_header",
    "caption": "caption", "footnote": "footnote", "page_header": "page_header", "page_footer": "page_footer",
    "list_item": "list_item", "formula": "formula", "code": "code", "reference": "reference",
    "document_index": "document_index",
}


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


class TableRules(BaseModel):
    """What counts as a table when a page is written out (a document's tables are built by these rules)."""

    model_config = ConfigDict(extra="forbid")

    single_cell: Literal["table", "text"] = Field("table", description="a table of one cell: a table, or its text "
                                                                       "as a text item")
    single_column: Literal["table", "lines"] = Field("table", description="a table of one column: a table, or its "
                                                                          "rows as the lines of a text item")
    merge_single_rows: bool = Field(False, description="a one-row table right after a table of the same width is "
                                                       "that table's next row")
    fill_holes: bool = Field(False, description="grid positions a short row leaves empty become empty cells")


class MarkdownRules(BaseModel):
    """The Markdown a rendering writes (``linecaster.document.to_markdown``)."""

    model_config = ConfigDict(extra="forbid")

    tables: Literal["html", "html-for-spans"] = Field(
        "html-for-spans", description="every table as HTML (rows and cells with their spans, header cells as <th>, "
                                      "line breaks as <br>), or Markdown tables and HTML only for spanning cells")
    escape: bool = Field(True, description="escape characters Markdown would read (underscores, HTML)")
    image_placeholder: str = Field("<!-- image -->", description="what a picture writes; '' for nothing")
    html_scripts: bool = Field(False, description="superscript, subscript and underline as <sup>, <sub>, <u>")
    escape_dollar: bool = Field(False, description="a $ that is no formula's written \\$, so that $…$ is always a "
                                                   "formula (needs the blocks' formula spans)")
    formula_display: Literal["$$", "$"] = Field("$$", description="a displayed formula between $$ and $$ on its own, "
                                                                  "or between $ and $ as an inline one")
    line_break: Literal["backslash", "spaces"] = Field("backslash", description="a line break inside a block: a "
                                                                                "backslash or two spaces at the "
                                                                                "line's end (both CommonMark)")


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
    tables: TableRules = Field(default_factory=TableRules, description="what counts as a table when written out")
    markdown: MarkdownRules = Field(default_factory=MarkdownRules, description="the Markdown a rendering writes")

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
    edits={"verbatim_txt": ["nfc", "joined"], "readable_txt": ["nfc", "joined", "normalized"],
           "readable_md": ["nfc", "joined", "normalized"]})


def policy_dict(p: RenderingPolicy) -> dict[str, Any]:
    return p.model_dump(mode="json", exclude_defaults=True)
