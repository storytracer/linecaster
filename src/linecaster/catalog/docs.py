"""The catalog's generated pages (``linecaster docs``, ``docs/catalog/``), one folder per kind: ``engines/``,
``models/``, ``presets/<step>/``, ``pipelines/``, ``recipes/``, ``policies/``, ``conventions/``,
``normalizations/``, ``strategies/``, ``vocabularies/``, and an index (``README.md``).

Nothing here is written by hand twice: facts come from the model, preset and recipe entries and from the
engines' and pipelines' source (``catalog.code``), prose from the documents' bodies. The pages quote no
measurements: linecaster's catalog holds no evidence records.
"""
from __future__ import annotations

import shutil
import unicodedata
from pathlib import Path

from linecaster.docs.common import GITHUB, HEADER, Links, table
from linecaster.catalog import code
from linecaster.catalog.registry import IN_PROCESS_ONLY, Catalog
from linecaster.catalog.schema import STEPS

STEP_TITLES = {"layout": "🗺️ Layout", "lines": "📏 Lines", "recognition": "👁️ Recognition", "tables": "📊 Tables",
               "formulas": "➗ Formulas", "image": "🖼️ Image", "normalization": "🔤 Normalization",
               "typography": "🔠 Typography", "recomposition": "📝 Recomposition", "composition": "📄 Composition",
               "import": "📥 Import", "tagging": "🏷️ Tagging"}
#: the preset sections of the index: one per step, page presets (VLMs reading whole pages) last
SECTIONS = (*((STEP_TITLES[s], s, False) for s in STEPS), ("🤖 Vision-language models, whole pages", "recognition", True))
KINDS = ("engines", "models", "presets", "pipelines", "recipes", "policies", "conventions", "normalizations",
         "strategies", "vocabularies")


def preset_path(c: Catalog, pid: str) -> str:
    return f"presets/{c.preset(pid).step}/{pid}.md"


def _md(text: str) -> str:
    """A docstring as Markdown: reST's double backticks become single ones."""
    return text.replace("``", "`")


_table = table


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


def preset_page(c: Catalog, pid: str) -> str:
    d, p = c.presets[pid]
    body = d.bodies["preset"][pid].strip()
    lines = [f"# {pid}", "", f"*Preset · {p.step} · {p.support}*", ""]
    if body:
        lines += [body, ""]
    if p.page_preset:
        lines += ["```bash", f"uv run launch.py {pid} IMAGES OUT", "```", ""]
    rows = [("Step", p.step + (f" (reads {p.capabilities.unit}s)" if p.capabilities.unit else "")),
            ("Engine", f"[`{p.engine}`](../../engines/{p.engine}.md)")]
    if p.model is not None:
        m = c.model(p.model.id)
        pin = m.pin(p.model.revision)
        rows += [("Model", f"[{m.version or m.id}](../../models/{m.id}.md)"),
                 ("Revision", f"[`{pin.revision}`]({_model_url(c, p)})"), ("License", m.license)]
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
    if p.by_script:
        lines += ["## Strategies by script", "", "Each decision is made by the strategy for the script around it; "
                  "`*` decides for every other script.", "",
                  *_table(("Script", "Preset"), [(f"`{code}`", f"[`{ref}`](../../{preset_path(c, ref.rsplit('@', 1)[0])})")
                                                 for code, ref in sorted(p.by_script.items())])]
    if p.provenance.derived_from:
        lines += ["## Provenance", "", *[f"- {x}" for x in p.provenance.derived_from], ""]
    return "\n".join(lines)


def model_page(c: Catalog, mid: str, out: Path, links: Links) -> str:
    d, m = c.models[mid]
    lines = [f"# {mid}", "", f"*Model · {m.version or mid} · {m.license}*", ""]
    body = d.bodies["model"][mid].strip()
    if body:
        lines += [body, ""]
    url = {"hf": f"https://huggingface.co/{m.source.ref}", "zenodo": f"https://doi.org/{m.source.ref}"}.get(
        m.source.kind, m.source.ref)
    rows = [("Source", f"[{m.source.ref}]({url})"), ("License", m.license)]
    for label, value in (("Languages", ", ".join(m.languages)), ("Scripts", ", ".join(m.scripts)),
                         ("Parameters", m.params or ""),
                         ("Derived from", "; ".join(f"{x.relation} of {x.ref}" for x in m.derived_from))):
        if value:
            rows.append((label, value))
    lines += _table(("", ""), rows)
    pins = [(f"`{pin.revision}`", pin.pinned, pin.tag or "", len(pin.files),
             f"[{Path(pin.card).name}]({links.to(d.root / 'models' / mid / pin.card, out / 'models')})") for pin in m.pins]
    lines += ["## Pins", "", "Each with the upstream card as published at that revision, verbatim.", "",
              *_table(("Revision", "Pinned", "Tag", "Files", "Card"), pins)]
    users = sorted(pid for pid, (_, p) in c.presets.items()
                   if (p.model and p.model.id == mid) or any(r.id == mid for r in p.submodels.values()))
    if users:
        lines += ["## Presets", "", *[f"- [`{pid}`](../{preset_path(c, pid)})" for pid in users], ""]
    return "\n".join(lines)


def engine_page(c: Catalog, e: code.Engine, out: Path, links: Links) -> str:
    lines = [f"# {e.id}", "", f"*Engine · {e.step or '-'} · package `{e.package}`*", "", _md(e.doc), ""]
    rows = [("Class", f"`{e.target}`"), ("Source", f"[{e.source.name}]({links.to(e.source, out / 'engines')})")]
    if e.capabilities.get("unit"):
        rows.append(("Reads", f"{e.capabilities['unit']}s"))
    if e.capabilities.get("produces"):
        rows.append(("Produces", ", ".join(e.capabilities["produces"])))
    if e.scripts:
        rows.append(("Scripts", "all" if e.scripts == ["*"] else ", ".join(e.scripts)))
    if e.id in IN_PROCESS_ONLY:
        rows.append(("Runs", "in the pipeline's process"))
    lines += _table(("", ""), rows)
    if e.options:
        lines += ["## Options", "", *_table(("Option", "Type", "Default", "Description"),
                                            [(f"`{o.name}`", f"`{o.type}`", f"`{o.default}`" if o.default else "",
                                              o.description) for o in e.options])]
    if e.adapters:
        lines += ["## Adapters", "", "Each preset names one in `options.adapter`: the request and the parsing of "
                                     "the answer.", "",
                  *_table(("Adapter", "Source"), [(f"`{a}`", f"[{src.name}]({links.to(src, out / 'engines')})")
                                                  for a, src in sorted(e.adapters.items())])]
    users = sorted(pid for pid, (_, p) in c.presets.items() if p.engine == e.id)
    if users:
        lines += ["## Presets", "", *[f"- [`{pid}`](../{preset_path(c, pid)})" for pid in users], ""]
    return "\n".join(lines)


def pipeline_page(c: Catalog, pl: code.Pipeline, out: Path, links: Links) -> str:
    shape = f"linecaster.pipelines.{pl.shape.stem}"
    lines = [f"# {pl.id}", "", f"*Pipeline · [`{pl.source.name}`]({links.to(pl.source, out / 'pipelines')}) · "
                               f"shape [`{shape}`]({links.to(pl.shape, out / 'pipelines')})*", "", _md(pl.doc), ""]
    if pl.slots:
        lines += ["## Slots", "", "Each slot takes a preset of that step; a recipe fills them all.", "",
                  *_table(("Slot", "Option"), [(slot, f"`--{opt}`") for slot, opt in pl.slots.items()])]
    if pl.options:
        lines += ["## Options", "", "Besides the options every pipeline shares (`linecaster.runtime.run`).", "",
                  *_table(("Option", "Values", "Default", "Description"),
                          [(f"`{o.name}`", o.type, f"`{o.default}`" if o.default not in ("", "None") else "",
                            o.description) for o in pl.options])]
    users = sorted(rid for rid, (_, r) in c.recipes.items() if r.pipeline == pl.id)
    if users:
        lines += ["## Recipes", "", *[f"- [`{rid}`](../recipes/{rid}.md)" for rid in users], ""]
    return "\n".join(lines)


def recipe_page(c: Catalog, rid: str) -> str:
    d, rc = c.recipes[rid]
    body = d.bodies["recipe"][rid].strip()
    lines = [f"# {rid}", "", f"*Recipe · pipeline [`{rc.pipeline}`](../pipelines/"
                             f"{rc.pipeline}.md) · {rc.support}*", ""]
    if body:
        lines += [body, ""]
    lines += ["```bash", f"uv run launch.py {rid} IMAGES OUT", "```", "",
              f"Its script, [`recipes/{rid}.py`]({GITHUB}/recipes/{rid}.py), is its environment: the engine packages "
              "its presets need. It runs without a checkout too:", "",
              "```bash", f"uv run https://raw.githubusercontent.com/storytracer/linecaster/main/recipes/{rid}.py IMAGES OUT",
              "```", ""]
    lines += _table(("Slot", "Preset"), [(slot, f"[`{ref}`](../{preset_path(c, ref.rsplit('@', 1)[0])})")
                                         for slot, ref in rc.presets.items()])
    if rc.options:
        lines += _table(("Option", "Value"), [(k, f"`{v}`") for k, v in rc.options.items()])
    if rc.provenance.derived_from:
        lines += ["## Provenance", "", *[f"- {x}" for x in rc.provenance.derived_from], ""]
    return "\n".join(lines)


def conventions_page(c: Catalog, cid: str) -> str:
    """A conventions entry: what it is, its parent, its prose, and its rules (match, decision, why)."""
    d, doc = c.conventions_entries[cid]
    resolved = c.conventions(doc.ref)
    parent = f" · extends [`{doc.extends}`]({doc.extends}.md)" if doc.extends else ""
    lines = [f"# {cid}", "", f"*Conventions · format `{doc.format}`{parent}*", "",
             _md(doc.description), "", f"Resolved: `{resolved.ref}`, {len(resolved.rules)} rules.", ""]
    if doc.source:
        lines += _table(("Written against", ""), [(k, _md(v)) for k, v in doc.source.items()])
    body = d.bodies["conventions"][cid].strip()
    if body:
        lines += [body, ""]
    lines += ["## Rules", "", *_table(("Rule", "Match", "Decision", "Why"), [
        (f"`{r.id}`", f"`{r.match.model_dump(exclude={'kind'}, exclude_none=True)}`",
         f"`{r.decision}`" + (f" `{r.params}`" if r.params else ""), _md(r.why)) for r in doc.rules])]
    if doc.disable:
        lines += ["## Disabled", "", *_table(("Rule", "Why"), [(f"`{k}`", _md(v)) for k, v in doc.disable.items()])]
    return "\n".join(lines)


def policy_page(c: Catalog, pid: str) -> str:
    """A rendering policy: its rules (what goes into which layer)."""
    _, doc = c.policies[pid]
    lines = [f"# {pid}", "", "*Rendering policy*", "", _md(doc.description), ""]
    lines += ["## Rules", "", *_table(("Role", "Production", "Status", "Layer"), [
        (r.role or "any", r.production or "any", r.status or "any", f"`{r.to}`") for r in doc.rules])]
    return "\n".join(lines)


def _chars(s: str) -> str:
    """Characters as shown in a page: as code where each is visible on its own (a letter, digit, punctuation or
    symbol), else as code points (a combining mark, a format character, a space: ``U+0640``)."""
    if s and all(unicodedata.category(c)[0] in "LNPS" for c in s):
        return f"`{s}`"
    return " ".join(f"U+{ord(c):04X}" for c in s) or "nothing"


def _rule(rule: dict) -> str:
    """A normalization's rule, in a line."""
    (kind, value), = rule.items()
    if kind == "map":
        shown = ", ".join(f"{_chars(k)} → {_chars(v)}" if v else f"{_chars(k)} removed"
                          for k, v in list(value.items())[:12])
        return f"map: {shown}" + (" …" if len(value) > 12 else "")
    if kind == "patterns":
        return f"{len(value)} pattern{'s' if len(value) != 1 else ''}: " + ", ".join(
            f"`{x['match']}`" for x in value[:4]) + (" …" if len(value) > 4 else "")
    if kind == "keep":
        what = [*value.get("categories", []), *value.get("ranges", [])]
        return f"keep: {', '.join(what)}" + (" and U+FFFD" if "\ufffd" in value.get("also", "") else "")
    return f"{kind}: `{value}`"


def normalization_page(c: Catalog, nid: str) -> str:
    """A normalization: what it does, for what, its rule."""
    _, doc = c.normalizations[nid]
    meta = [f"for {' and '.join(doc.use)}", f"scripts {', '.join(doc.scripts)}"]
    if doc.languages:
        meta.append(f"languages {', '.join(doc.languages)} (language-specific)")
    lines = [f"# {nid}", "", f"*Normalization · {' · '.join(meta)}*", "", _md(doc.description), "",
             f"Rule: {_rule(doc.rule.model_dump(mode='json', exclude_none=True))}", ""]
    if doc.subsumes:
        lines += ["Includes the effect of " + ", ".join(f"[`{x}`]({x}.md)" for x in doc.subsumes) + ".", ""]
    users = sorted(sid for sid, (_, st) in c.strategies.items() if nid in st.normalizations)
    if users:
        lines += ["Strategies with it: " + ", ".join(f"[`{x}`](../strategies/{x}.md)" for x in users) + ".", ""]
    return "\n".join(lines)


def strategy_page(c: Catalog, sid: str) -> str:
    """A strategy: its normalizations in order."""
    _, doc = c.strategies[sid]
    lines = [f"# {sid}", "", f"*Strategy · for {doc.use}*", "", _md(doc.description), "", "## Normalizations", "",
             *_table(("", "Normalization", "What it does"), [
                 (str(k + 1), f"[`{n}`](../normalizations/{n}.md)", _md(c.normalizations[n][1].description))
                 for k, n in enumerate(doc.normalizations)])]
    return "\n".join(lines)


def _terms(terms: dict, answers: dict | None = None) -> list[str]:
    """A vocabulary's values (or reasons) as sections: the definition, what counts and what does not."""
    out = []
    for name, t in terms.items():
        answer = f" (answer `{answers[name]}`)" if answers and name in answers else ""
        out += [f"### `{name}`{answer}", "", _md(t.definition), ""]
        if t.counts:
            out += ["Counts:", "", *[f"- {_md(x)}" for x in t.counts], ""]
        if t.does_not_count:
            out += ["Does not count:", "", *[f"- {_md(x)}" for x in t.does_not_count], ""]
    return out


def vocabulary_page(c: Catalog, scheme: str) -> str:
    """A vocabulary: what its scheme classifies, each value's definition, what counts and what does not; the content
    roles' PAGE-XML types, region labels and default layers (``linecaster.data.policy.ROLES``)."""
    _, doc = c.vocabularies[scheme]
    kind = "property scheme, yes or no" if doc.property else ("open scheme" if doc.open else "closed scheme")
    lines = [f"# {scheme}", "", f"*Vocabulary · {kind} · classifies {', '.join(f'{t}s' for t in doc.targets)}*", "",
             _md(doc.description), ""]
    if doc.open:
        lines += [f"Its values match `{doc.pattern}`.", ""]
    if doc.values:
        lines += ["## Values", "", *_terms(doc.values, doc.answers)]
    if doc.reasons:
        lines += ["## Reasons", "", "Why something present in a source is no text of the page (a classification's "
                  "`reason`).", "", *_terms(doc.reasons)]
    if scheme == "role":
        from linecaster.data.policy import ROLES

        lines += ["## Mappings", "", *_table(("Role", "PAGE-XML", "Region label", "Default layer"), [
            (f"`{r}`", f"`{page}`", f"`{label}`", layer) for r, (page, label, layer) in ROLES.items()])]
    if doc.provenance:
        lines += ["## Provenance", "", *[f"- {_md(x)}" for x in doc.provenance], ""]
    return "\n".join(lines)


def index_page(c: Catalog, engines: dict, pipelines: dict) -> str:
    lines = ["# Catalog", "", "Generated by `linecaster docs` from the catalog's entries and the "
             "engines' and pipelines' source.", ""]
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
    for title, step, page in SECTIONS:
        ps = sorted(pid for pid, (_, p) in c.presets.items() if p.step == step and p.page_preset == page)
        if not ps:
            continue
        rows = [(f"[`{pid}`]({preset_path(c, pid)})", f"`{c.preset(pid).engine}`",
                 c.model(c.preset(pid).model.id).license if c.preset(pid).model else "-") for pid in ps]
        lines += [f"### {title}", "", *_table(("Preset", "Engine", "License"), rows)]
    if c.conventions_entries:
        lines += ["## 🧭 Conventions", "", *_table(("Conventions", "Format", "Extends"), [
            (f"[`{cid}`](conventions/{cid}.md)", f"`{doc.format}`", f"`{doc.extends}`" if doc.extends else "-")
            for cid, (_, doc) in sorted(c.conventions_entries.items())])]
    if c.policies:
        lines += ["## 🗂️ Rendering policies", "", *_table(("Policy", "Description"), [
            (f"[`{pid}`](policies/{pid}.md)", _md(doc.description.split(". ")[0])) for pid, (_, doc)
            in sorted(c.policies.items())])]
    if c.strategies:
        lines += ["## ✍️ Strategies", "", "Texts are written `literal` (the readings as given) or by a strategy of "
                  "normalizations; lanes are strategies for comparison.", "",
                  *_table(("Strategy", "For", "Normalizations"), [
                      (f"[`{sid}`](strategies/{sid}.md)", doc.use, ", ".join(f"`{n}`" for n in doc.normalizations))
                      for sid, (_, doc) in sorted(c.strategies.items())])]
    if c.vocabularies:
        lines += ["## 📖 Vocabularies", "", "What the values of a classification scheme mean; the taggers' questions "
                  "are generated from them.", "", *_table(("Scheme", "Values", "Classifies"), [
                      (f"[`{sid}`](vocabularies/{sid}.md)", "open" if doc.open else ", ".join(
                          f"`{v}`" for v in doc.values), ", ".join(doc.targets))
                      for sid, (_, doc) in sorted(c.vocabularies.items())])]
    if c.normalizations:
        lines += ["## 🔤 Normalizations", "", *_table(("Normalization", "For", "Languages"), [
            (f"[`{nid}`](normalizations/{nid}.md)", ", ".join(doc.use), ", ".join(doc.languages) or "-")
            for nid, (_, doc) in sorted(c.normalizations.items())])]
    lines += ["## 📦 Models", "", *_table(("Model", "Upstream", "License"), [
        (f"[`{mid}`](models/{mid}.md)", m.version or "", m.license) for mid, (_, m) in sorted(c.models.items())])]
    return "\n".join(lines)


def pages(c: Catalog, out: str | Path, links: Links | None = None, repo: Path | None = code.REPO) -> dict[str, str]:
    """Every page of the catalog by its path below ``out`` (the catalog's folder of the docs), each with the generated
    header. Engine and pipeline pages need the repository checkout (``repo``); ``links`` default to links relative
    to ``out``."""
    out = Path(out)
    links = links or Links(out, repo)
    engines = code.engines(repo) if repo is not None and repo.exists() else {}
    pipelines = code.pipelines(repo) if repo is not None and repo.exists() else {}
    found = {}
    for pid in c.presets:
        found[preset_path(c, pid)] = preset_page(c, pid)
    for mid in c.models:
        found[f"models/{mid}.md"] = model_page(c, mid, out, links)
    for rid in c.recipes:
        found[f"recipes/{rid}.md"] = recipe_page(c, rid)
    for cid in c.conventions_entries:
        found[f"conventions/{cid}.md"] = conventions_page(c, cid)
    for pid in c.policies:
        found[f"policies/{pid}.md"] = policy_page(c, pid)
    for nid in c.normalizations:
        found[f"normalizations/{nid}.md"] = normalization_page(c, nid)
    for sid in c.strategies:
        found[f"strategies/{sid}.md"] = strategy_page(c, sid)
    for sid in c.vocabularies:
        found[f"vocabularies/{sid}.md"] = vocabulary_page(c, sid)
    for eid, e in engines.items():
        found[f"engines/{eid}.md"] = engine_page(c, e, out, links)
    for pid, pl in pipelines.items():
        found[f"pipelines/{pid}.md"] = pipeline_page(c, pl, out, links)
    found["README.md"] = index_page(c, engines, pipelines)
    return {rel: f"{HEADER}\n{text.rstrip(chr(10))}\n" for rel, text in sorted(found.items())}


def write(c: Catalog, out: str | Path, repo: Path | None = code.REPO) -> list[Path]:
    """Every page, into ``out``; the folders of the kinds are generated and replaced. Engine and pipeline pages
    need the repository checkout (``repo``). ``linecaster docs`` writes these with the rest of the docs
    (``linecaster.docs``)."""
    out = Path(out)
    for comp in KINDS:
        shutil.rmtree(out / comp, ignore_errors=True)
    written = []
    for rel, text in pages(c, out, repo=repo).items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
