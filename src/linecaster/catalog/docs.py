"""Generated documentation from the catalogue, one folder per component: ``engines/``, ``models/``,
``presets/<step>/``, ``pipelines/``, ``recipes/``, an index (``README.md``), and the README's tables.

Nothing here is written by hand twice: facts come from the model, preset and recipe documents and from the
engines' and pipelines' source (``catalog.code``), numbers from the evidence records (each with its source),
prose from the documents' bodies.
"""
from __future__ import annotations

import os
import shutil
from collections import defaultdict
from pathlib import Path

from . import code
from .registry import Catalog
from .schema import STEPS

STEP_TITLES = {"page": "🤖 Vision-language models, whole pages", "layout": "🗺️ Layout", "lines": "📏 Lines",
               "recognition": "👁️ Recognition", "tables": "📊 Tables", "formulas": "➗ Formulas"}
SOURCE_NAMES = {"own-run": "Linecaster run", "board": "BHL board", "card-claim": "model card claim",
                "vendor-benchmark": "vendor benchmark"}
MARK_START, MARK_END = "<!-- catalog:start -->", "<!-- catalog:end -->"
COMPONENTS = ("engines", "models", "presets", "pipelines", "recipes")


def preset_path(c: Catalog, pid: str) -> str:
    return f"presets/{c.preset(pid).step}/{pid}.md"


def _md(text: str) -> str:
    """A docstring as Markdown: reST's double backticks become single ones."""
    return text.replace("``", "`")


def _table(header: tuple, rows: list[tuple]) -> list[str]:
    cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    return [f"| {' | '.join(header)} |", f"|{'---|' * len(header)}",
            *[f"| {' | '.join(cell(v) for v in r)} |" for r in rows], ""]


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


def preset_page(c: Catalog, pid: str, evs: list) -> str:
    d, p = c.presets[pid]
    body = d.preset_bodies[pid].strip()
    lines = [f"# {pid}", "", f"*Preset · edition {p.edition} · {p.step} · {p.support}*", ""]
    if body:
        lines += [body, ""]
    rows = [("Step", p.step + (f" (reads {p.capabilities.unit}s)" if p.capabilities.unit else "")),
            ("Engine", f"[`{p.engine}`](../../engines/{p.engine}.md)")]
    if p.model is not None:
        m = c.model(p.model.id)
        pin = m.pin(p.model.revision)
        rows += [("Model", f"[{m.version or m.id}](../../models/{m.id}.md)"),
                 ("Revision", f"[`{pin.revision}`]({_model_url(c, p)})"), ("Licence", m.license)]
    for role, ref in p.submodels.items():
        rows.append((f"Model ({role})", f"[{ref.id}](../../models/{ref.id}.md) `{ref.revision[:12]}`"))
    if p.serve is not None:
        rows.append(("Server", f"{p.serve.server} {p.serve.version or ''}".strip()))
        if p.serve.image:
            rows.append(("Image", f"`{p.serve.image}`"))
    if p.capabilities.produces:
        rows.append(("Produces", ", ".join(p.capabilities.produces)))
    if p.superseded_by:
        rows.append(("Superseded by", p.superseded_by))
    lines += _table(("", ""), rows)
    if p.options:
        lines += ["## Options", "", *_table(("Option", "Value"), [(k, f"`{v}`") for k, v in p.options.items()])]
    lines += _evidence_table(evs)
    if p.provenance.derived_from:
        lines += ["## Provenance", "", *[f"- {x}" for x in p.provenance.derived_from], ""]
    return "\n".join(lines)


def _evidence_table(evs) -> list[str]:
    if not evs:
        return []
    rows = [(e.date, SOURCE_NAMES[e.source], e.dataset + (f" ({e.context})" if e.context else ""),
             ", ".join(f"{k} {v:g}" for k, v in e.metrics.items())) for e in evs]
    return ["## Evidence", "", *_table(("Date", "Source", "Dataset", "Result"), rows)]


def model_page(c: Catalog, mid: str, out: Path) -> str:
    d, m = c.models[mid]
    lines = [f"# {mid}", "", f"*Model · {m.version or mid} · {m.license}*", ""]
    body = d.model_bodies[mid].strip()
    if body:
        lines += [body, ""]
    url = {"hf": f"https://huggingface.co/{m.source.ref}", "zenodo": f"https://doi.org/{m.source.ref}"}.get(
        m.source.kind, m.source.ref)
    rows = [("Source", f"[{m.source.ref}]({url})"), ("Licence", m.license)]
    for label, value in (("Languages", ", ".join(m.languages)), ("Scripts", ", ".join(m.scripts)),
                         ("Parameters", m.params or ""),
                         ("Derived from", "; ".join(f"{x.relation} of {x.ref}" for x in m.derived_from))):
        if value:
            rows.append((label, value))
    lines += _table(("", ""), rows)
    pins = [(f"`{pin.revision}`", pin.pinned, pin.tag or "", len(pin.files),
             f"[{Path(pin.card).name}]({_rel(d.root / 'models' / mid / pin.card, out / 'models')})") for pin in m.pins]
    lines += ["## Pins", "", "Each with the upstream card as published at that revision, verbatim.", "",
              *_table(("Revision", "Pinned", "Tag", "Files", "Card"), pins)]
    users = sorted(pid for pid, (_, p) in c.presets.items()
                   if (p.model and p.model.id == mid) or any(r.id == mid for r in p.submodels.values()))
    if users:
        lines += ["## Presets", "", *[f"- [`{pid}`](../{preset_path(c, pid)})" for pid in users], ""]
    return "\n".join(lines)


def engine_page(c: Catalog, e: code.Engine, out: Path) -> str:
    lines = [f"# {e.id}", "", f"*Engine · {e.step or '-'} · package `{e.package}`*", "", _md(e.doc), ""]
    rows = [("Class", f"`{e.target}`"), ("Source", f"[{e.source.name}]({_rel(e.source, out / 'engines')})")]
    if e.capabilities.get("unit"):
        rows.append(("Reads", f"{e.capabilities['unit']}s"))
    if e.capabilities.get("produces"):
        rows.append(("Produces", ", ".join(e.capabilities["produces"])))
    lines += _table(("", ""), rows)
    if e.options:
        lines += ["## Options", "", *_table(("Option", "Type", "Default", "Description"),
                                            [(f"`{o.name}`", f"`{o.type}`", f"`{o.default}`" if o.default else "",
                                              o.description) for o in e.options])]
    if e.adapters:
        lines += ["## Adapters", "", "Each preset names one in `options.adapter`: the request and the parsing of "
                                     "the answer.", "",
                  *_table(("Adapter", "Source"), [(f"`{a}`", f"[{src.name}]({_rel(src, out / 'engines')})")
                                                  for a, src in sorted(e.adapters.items())])]
    users = sorted(pid for pid, (_, p) in c.presets.items() if p.engine == e.id)
    if users:
        lines += ["## Presets", "", *[f"- [`{pid}`](../{preset_path(c, pid)})" for pid in users], ""]
    return "\n".join(lines)


def pipeline_page(c: Catalog, pl: code.Pipeline, out: Path) -> str:
    lines = [f"# {pl.id}", "", f"*Pipeline · [`{pl.source.name}`]({_rel(pl.source, out / 'pipelines')})*", "",
             _md(pl.doc), ""]
    if pl.slots:
        lines += ["## Slots", "", "Each slot takes a preset of that step; a recipe fills them all.", "",
                  *_table(("Slot", "Option"), [(slot, f"`--{opt}`") for slot, opt in pl.slots.items()])]
    if pl.options:
        lines += ["## Options", "", "Besides the options every pipeline shares (`linecaster.run`).", "",
                  *_table(("Option", "Values", "Default", "Description"),
                          [(f"`{o.name}`", o.type, f"`{o.default}`" if o.default not in ("", "None") else "",
                            o.description) for o in pl.options])]
    users = sorted(rid for rid, (_, r) in c.recipes.items() if r.pipeline == pl.id)
    if users:
        lines += ["## Recipes", "", *[f"- [`{rid}`](../recipes/{rid}.md)" for rid in users], ""]
    return "\n".join(lines)


def recipe_page(c: Catalog, rid: str, evs: list) -> str:
    d, rc = c.recipes[rid]
    body = d.recipe_bodies[rid].strip()
    lines = [f"# {rid}", "", f"*Recipe · edition {rc.edition} · pipeline [`{rc.pipeline}`](../pipelines/"
                             f"{rc.pipeline}.md) · {rc.support}*", ""]
    if body:
        lines += [body, ""]
    lines += _table(("Slot", "Preset"), [(slot, f"[`{ref}`](../{preset_path(c, ref.rsplit('@', 1)[0])})")
                                         for slot, ref in rc.presets.items()])
    if rc.options:
        lines += _table(("Option", "Value"), [(k, f"`{v}`") for k, v in rc.options.items()])
    lines += _evidence_table(evs)
    if rc.provenance.derived_from:
        lines += ["## Provenance", "", *[f"- {x}" for x in rc.provenance.derived_from], ""]
    return "\n".join(lines)


def index_page(c: Catalog, evs: dict, engines: dict, pipelines: dict) -> str:
    lines = ["# Catalogue", "", "Generated by `linecaster catalog docs` from the catalogue's documents and the "
             "engines' and pipelines' source. CER is the reading-lane character error rate of Linecaster's own "
             "latest run, where there is one.", ""]
    if c.recipes:
        lines += ["## 🍳 Recipes", "", *_table(("Recipe", "Pipeline", "Support"), [
            (f"[`{rid}`](recipes/{rid}.md)", f"`{r.pipeline}`", r.support) for rid, (_, r) in sorted(c.recipes.items())])]
    if pipelines:
        lines += ["## 🧩 Pipelines", "", *_table(("Pipeline", "Slots"), [
            (f"[`{pid}`](pipelines/{pid}.md)", ", ".join(pl.slots)) for pid, pl in sorted(pipelines.items())])]
    if engines:
        lines += ["## ⚙️ Engines", "", *_table(("Engine", "Step", "Package"), [
            (f"[`{eid}`](engines/{eid}.md)", e.step or "-", f"`{e.package}`") for eid, e in sorted(engines.items())])]
    lines += ["## 🎛️ Presets", ""]
    for step in STEPS:
        ps = sorted(pid for pid, (_, p) in c.presets.items() if p.step == step)
        if not ps:
            continue
        rows = []
        for pid in ps:
            p = c.preset(pid)
            cer = _metric(evs.get(pid, []))
            rows.append((f"[`{pid}`]({preset_path(c, pid)})", f"`{p.engine}`",
                         c.model(p.model.id).license if p.model else "-", "" if cer is None else f"{cer:.4f}"))
        lines += [f"### {STEP_TITLES[step]}", "", *_table(("Preset", "Engine", "Licence", "CER"), rows)]
    lines += ["## 📦 Models", "", *_table(("Model", "Upstream", "Licence"), [
        (f"[`{mid}`](models/{mid}.md)", m.version or "", m.license) for mid, (_, m) in sorted(c.models.items())])]
    return "\n".join(lines)


def readme_tables(c: Catalog, docs_rel: str) -> str:
    """The README's tables: one section per step, one preset per row, then the recipes."""
    lines = []
    for step in STEPS:
        ps = sorted(pid for pid, (_, p) in c.presets.items() if p.step == step and p.support != "legacy")
        if not ps:
            continue
        rows = []
        for pid in ps:
            p = c.preset(pid)
            model = "-"
            if p.model is not None:
                m = c.model(p.model.id)
                model = f"[{m.version or m.id}]({_model_url(c, p)})"
            rows.append((f"[`{pid}`]({docs_rel}/{preset_path(c, pid)})", model))
        lines += [f"### {STEP_TITLES[step]}", "", *_table(("Preset", "Model"), rows)]
    if c.recipes:
        lines += ["### 🍳 Recipes", "", *_table(("Recipe", "Pipeline", "Presets"), [
            (f"[`{rid}`]({docs_rel}/recipes/{rid}.md)", f"`{r.pipeline}`", ", ".join(f"`{x}`" for x in r.presets.values()))
            for rid, (_, r) in sorted(c.recipes.items())])]
    return "\n".join(lines).rstrip("\n")


def _rel(path: Path, frm: Path) -> str:
    return os.path.relpath(Path(path).resolve(), Path(frm).resolve())


def write(c: Catalog, out: str | Path, readme: str | Path | None = None, repo: Path | None = code.REPO) -> list[Path]:
    """Every page, into ``out``; the component folders are generated and replaced. Engine and pipeline pages
    need the repository checkout (``repo``)."""
    out = Path(out)
    for comp in COMPONENTS:
        shutil.rmtree(out / comp, ignore_errors=True)
    evs = _evidence(c)
    engines = code.engines(repo) if repo is not None and repo.exists() else {}
    pipelines = code.pipelines(repo) if repo is not None and repo.exists() else {}
    pages = {}
    for pid in c.presets:
        pages[preset_path(c, pid)] = preset_page(c, pid, evs.get(pid, []))
    for mid in c.models:
        pages[f"models/{mid}.md"] = model_page(c, mid, out)
    for rid in c.recipes:
        pages[f"recipes/{rid}.md"] = recipe_page(c, rid, evs.get(rid, []))
    for eid, e in engines.items():
        pages[f"engines/{eid}.md"] = engine_page(c, e, out)
    for pid, pl in pipelines.items():
        pages[f"pipelines/{pid}.md"] = pipeline_page(c, pl, out)
    pages["README.md"] = index_page(c, evs, engines, pipelines)
    written = []
    for rel, text in sorted(pages.items()):
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
        written.append(path)
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
