"""Generated documentation from the catalogue: an index, one page per preset, and the README's model tables.

Nothing here is written by hand twice: facts come from the model and preset documents, numbers from the
evidence records (each with its source), prose from the documents' bodies.
"""
from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from .registry import Catalog
from .schema import STEPS

STEP_TITLES = {"page": "🤖 Vision-language models, whole pages", "layout": "🗺️ Layout", "lines": "📏 Lines",
               "recognition": "👁️ Recognition", "tables": "📊 Tables", "formulas": "➗ Formulas"}
SOURCE_NAMES = {"own-run": "Linecaster run", "board": "BHL board", "card-claim": "model card claim",
                "vendor-benchmark": "vendor benchmark"}
MARK_START, MARK_END = "<!-- catalog:start -->", "<!-- catalog:end -->"


def _model_url(c: Catalog, p) -> str | None:
    if p.model is None:
        return None
    m = c.model(p.model.id)
    if m.source.kind == "hf":
        return f"https://huggingface.co/{m.source.ref}/tree/{p.model.revision}"
    if m.source.kind == "git":
        return f"{m.source.ref}/tree/{p.model.revision}"
    if m.source.kind == "zenodo":
        return f"https://doi.org/{m.source.ref}"
    return m.source.ref


def _evidence(c: Catalog) -> dict[str, list]:
    by = defaultdict(list)
    for d in c.dirs:
        for _, ev in d.evidence:
            by[ev.subject.rsplit("@", 1)[0]].append(ev)
    for v in by.values():
        v.sort(key=lambda e: (e.date, e.source), reverse=True)
    return by


def _metric(evs, name="cer_reading", source="own-run"):
    for e in evs:
        if e.source == source and name in e.metrics:
            return e.metrics[name]
    return None


def _first_paragraph(body: str) -> str:
    for para in body.strip().split("\n\n"):
        para = para.strip()
        if para and not para.startswith("#"):
            return " ".join(para.split())
    return ""


def preset_page(c: Catalog, pid: str, evs: list, rel_root: str) -> str:
    d, p = c.presets[pid]
    body = d.preset_bodies[pid].strip()
    lines = [f"# {pid}", "", f"*Edition {p.edition} · {p.step} · {p.support}*", ""]
    if body:
        lines += [body, ""]
    rows = [("Step", p.step + (f" (reads {p.capabilities.unit}s)" if p.capabilities.unit else "")),
            ("Engine", f"`{p.engine.kind}`")]
    if p.model is not None:
        m = c.model(p.model.id)
        pin = m.pin(p.model.revision)
        card = os.path.relpath(d.root / "models" / m.id / pin.card, rel_root)
        rows += [("Model", f"[{m.version or m.id}]({_model_url(c, p)})"), ("Revision", f"`{pin.revision}`"),
                 ("Upstream card", f"[{pin.card}]({card}) (verbatim, at that revision)"),
                 ("Licence", m.license)]
        if m.languages:
            rows.append(("Languages", ", ".join(m.languages)))
        if m.scripts:
            rows.append(("Scripts", ", ".join(m.scripts)))
        if m.derived_from:
            rows.append(("Derived from", "; ".join(f"{x.relation} of {x.ref}" for x in m.derived_from)))
    if p.serve is not None:
        rows.append(("Server", f"{p.serve.server} {p.serve.version or ''}".strip()))
        if p.serve.image:
            rows.append(("Image", f"`{p.serve.image}`"))
    if p.capabilities.produces:
        rows.append(("Produces", ", ".join(p.capabilities.produces)))
    if p.superseded_by:
        rows.append(("Superseded by", p.superseded_by))
    lines += ["| | |", "|---|---|", *[f"| {k} | {v} |" for k, v in rows], ""]
    lines += _evidence_table(evs)
    if p.provenance.derived_from:
        lines += ["## Provenance", "", *[f"- {x}" for x in p.provenance.derived_from], ""]
    return "\n".join(lines)


def _evidence_table(evs) -> list[str]:
    if not evs:
        return []
    out = ["## Evidence", "", "| Date | Source | Dataset | Result |", "|---|---|---|---|"]
    for e in evs:
        res = ", ".join(f"{k} {v:g}" for k, v in e.metrics.items())
        ctx = f" ({e.context})" if e.context else ""
        out.append(f"| {e.date} | {SOURCE_NAMES[e.source]} | {e.dataset}{ctx} | {res} |")
    return out + [""]


def recipe_page(c: Catalog, rid: str, evs: list) -> str:
    d, rc = c.recipes[rid]
    body = d.recipe_bodies[rid].strip()
    lines = [f"# {rid}", "", f"*Recipe · edition {rc.edition} · pipeline `{rc.pipeline}` · {rc.support}*", ""]
    if body:
        lines += [body, ""]
    lines += ["| Slot | Preset |", "|---|---|"]
    lines += [f"| {slot} | [`{ref}`]({ref.rsplit('@', 1)[0]}.md) |" for slot, ref in rc.presets.items()]
    lines.append("")
    if rc.options:
        lines += ["| Option | Value |", "|---|---|", *[f"| {k} | `{v}` |" for k, v in rc.options.items()], ""]
    lines += _evidence_table(evs)
    if rc.provenance.derived_from:
        lines += ["## Provenance", "", *[f"- {x}" for x in rc.provenance.derived_from], ""]
    return "\n".join(lines)


def index_page(c: Catalog, evs: dict) -> str:
    lines = ["# Catalogue", "", "Generated by `linecaster catalog docs` from the model, preset and evidence documents.",
             "CER is the reading-lane character error rate of Linecaster's own latest run, where there is one.", ""]
    for step in STEPS:
        ps = sorted(pid for pid, (_, p) in c.presets.items() if p.step == step)
        if not ps:
            continue
        lines += [f"## {STEP_TITLES[step]}", "", "| Preset | Licence | CER |", "|---|---|---|"]
        for pid in ps:
            p = c.preset(pid)
            lic = c.model(p.model.id).license if p.model else "-"
            cer = _metric(evs.get(pid, []))
            lines.append(f"| [{pid}]({pid}.md) | {lic} | {'' if cer is None else f'{cer:.4f}'} |")
        lines.append("")
    return "\n".join(lines)


def _recipe_rows(c: Catalog, link) -> list[str]:
    rows = []
    for rid in sorted(c.recipes):
        rc = c.recipe(rid)
        rows.append(f"| [`{rid}`]({link(rid)}) | `{rc.pipeline}` | " + ", ".join(f"`{r}`" for r in rc.presets.values()) + " |")
    return rows


def readme_tables(c: Catalog, docs_rel: str) -> str:
    """The README's model tables: one section per step, one preset per row, then the recipes."""
    lines = []
    for step in STEPS:
        ps = sorted(pid for pid, (_, p) in c.presets.items() if p.step == step and p.support != "legacy")
        if not ps:
            continue
        lines += [f"### {STEP_TITLES[step]}", "", "| Preset | Model |", "|---|---|"]
        for pid in ps:
            p = c.preset(pid)
            model = "-"
            if p.model is not None:
                m = c.model(p.model.id)
                model = f"[{m.version or m.id}]({_model_url(c, p)})"
            lines.append(f"| [`{pid}`]({docs_rel}/{pid}.md) | {model} |")
        lines.append("")
    if c.recipes:
        lines += ["### 🍳 Recipes", "", "| Recipe | Pipeline | Presets |", "|---|---|---|",
                  *_recipe_rows(c, lambda rid: f"{docs_rel}/{rid}.md"), ""]
    return "\n".join(lines).rstrip("\n")


def write(c: Catalog, out: str | Path, readme: str | Path | None = None) -> list[Path]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    evs = _evidence(c)
    written = []
    for pid in sorted(c.presets):
        path = out / f"{pid}.md"
        path.write_text(preset_page(c, pid, evs.get(pid, []), str(out)), encoding="utf-8")
        written.append(path)
    for rid in sorted(c.recipes):
        path = out / f"{rid}.md"
        path.write_text(recipe_page(c, rid, evs.get(rid, [])), encoding="utf-8")
        written.append(path)
    (out / "README.md").write_text(index_page(c, evs), encoding="utf-8")
    written.append(out / "README.md")
    if readme is not None:
        readme = Path(readme)
        text = readme.read_text(encoding="utf-8")
        if MARK_START in text and MARK_END in text:
            head, rest = text.split(MARK_START, 1)
            _, tail = rest.split(MARK_END, 1)
            rel = os.path.relpath(out, readme.parent)
            readme.write_text(f"{head}{MARK_START}\n{readme_tables(c, rel)}\n{MARK_END}{tail}", encoding="utf-8")
            written.append(readme)
    return written
