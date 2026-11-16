"""The ``linecaster`` command."""
from __future__ import annotations

import argparse
import json
import sys

from .errors import CatalogError, LinecasterError, PipelineConfigError, exit_code


def _serve(a) -> None:
    from .serve import Hosted, serve

    hosted = []
    if a.config:
        with open(a.config) as f:
            for m in json.load(f)["models"]:
                if m.get("preset"):        # a catalog preset, with options over the preset's
                    from .catalog.registry import engine_spec

                    spec, kw, r = engine_spec(m["preset"], served=True)
                    hosted.append(Hosted(m["name"], spec, {**kw, **m.get("overrides", {})},
                                         m.get("max_queue", a.max_queue), preset=r.ref, preset_sha256=r.sha256))
                else:
                    hosted.append(Hosted(m["name"], m["spec"], m.get("kwargs", {}), m.get("max_queue", a.max_queue)))
    kwargs = dict(kv.split("=", 1) for kv in a.kwargs)
    for kv in a.preset:
        from .catalog.registry import engine_spec

        name, ref = kv.split("=", 1)
        spec, kw, r = engine_spec(ref, served=True)
        kw.update(json.loads(kwargs.pop(name, "{}")))          # overrides, merged over the preset's options
        hosted.append(Hosted(name, spec, kw, a.max_queue, preset=r.ref, preset_sha256=r.sha256))
    for m in a.model:
        name, spec = m.split("=", 1)
        hosted.append(Hosted(name, spec, json.loads(kwargs.get(name, "{}")), a.max_queue))
    if not hosted:
        sys.exit("linecaster serve: no models (use --preset NAME=ID, --config or --model NAME=module:Class)")
    serve(hosted, a.host, a.port, a.decode_workers, a.traces, decoded_gb=a.decoded_gb)


def _traces(a) -> None:
    from .tracing.report import read_spans, render, summarize

    spans = read_spans(a.out)
    if not spans:
        sys.exit(f"linecaster traces: no traces in {a.out.rstrip('/')}/traces")
    report = summarize(spans, by=a.by, slowest=a.slowest)
    print(json.dumps(report, indent=1) if a.json else render(report), end="" if not a.json else "\n")


def _ago(seconds: float) -> str:
    from .runtime.console import duration

    return duration(seconds).replace(" ", "")


def _table(rows: list[tuple]) -> list[str]:
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return ["  " + "  ".join(str(x).ljust(w) for x, w in zip(r, widths)).rstrip() for r in rows]


def render_broker(report: dict) -> str:
    """Returns ``linecaster broker status``'s text for a ``linecaster.broker.survey_all`` report: the format, the
    workers, the slots per machine and per kind its resources held, free, blocked per scope and broken."""
    from .broker import FORMAT
    from .net.proxies import TURN

    now = report["now"]
    fmt = report["format"] or "none (no broker.json)"
    lines = [f"broker {report['path']}", f"  format {fmt}" + ("" if report["format"] in (FORMAT, None) else
                                                           f" (this linecaster knows {FORMAT})")
             + f", lease time {_ago(report['lease_ttl'])}", ""]
    workers = report["workers"]
    live = sum(w["live"] for w in workers)
    lines.append(f"workers: {live} live, {len(workers) - live} stale")
    if workers:
        lines += _table([("worker", "machine", "run", "renewed", "")]
                        + [(w["worker"], w["machine"] or "-", w["run"] or "-", f"{_ago(w['age'])} ago",
                            "" if w["live"] else "stale") for w in workers])
    lines.append("")
    slots = report["slots"]
    lines.append(f"slots: {sum(c['live'] for c in slots.values())} live, "
                 f"{sum(c['stale'] for c in slots.values())} stale")
    if slots:
        lines += _table([("machine", "live", "stale")] + [(m, c["live"], c["stale"]) for m, c in slots.items()])
    for kind, k in report["kinds"].items():
        lines += ["", f"{kind}: {k['resources']} known"]
        broken = k["broken"]
        lines += _table([("held", "stale", "free", "broken", "expired marks"),
                         (k["held"]["live"], k["held"]["stale"], k["free"],
                          f"{broken['resources']} (until in {_ago(broken['until'] - now)})" if broken else 0,
                          k["expired_marks"])])
        blocked = {s: b for s, b in k["blocked"].items() if not s.startswith(TURN)}   # hand-overs, no blocks
        if blocked:
            lines += _table([("blocked at", kind, "until")]
                            + [(scope, b["resources"], f"in {_ago(b['until'] - now)}")
                               for scope, b in blocked.items()])
    return "\n".join(lines) + "\n"


def _broker(a) -> None:
    try:
        _broker_action(a)
    except ImportError as e:                # fsspec's: the path's filesystem is not installed (gs:// without gcsfs)
        raise PipelineConfigError(f"{a.path}: {e}") from None


def _broker_action(a) -> None:
    from . import broker

    if a.action == "status":
        report = broker.survey_all(a.path)
        print(json.dumps(report, indent=1) if a.json else render_broker(report), end="\n" if a.json else "")
        return

    if a.action == "purge":
        def confirm_purge(result: dict) -> bool:
            removed = result["removed"]
            print(f"purge {result['path']}: " + ", ".join(f"{len(removed[c])} {c}" for c in broker.PURGED)
                  + f"; live: {result['live_workers']} workers, {result['live_marks']} marks", file=sys.stderr)
            if result["live_workers"]:
                print("live workers: a run may still use the broker", file=sys.stderr)
            return _ask(a, "Remove all of them?")

        result = broker.purge(a.path, dry_run=a.dry_run, confirm=confirm_purge)
        _report_removed(a, result, broker.PURGED)
        return

    def confirm(live: list[dict]) -> bool:
        print(f"{len(live)} live files (renewed within the lease time, or marks not expired); a run may still use "
              f"the broker:", file=sys.stderr)
        for f in live:
            print(f"  {f['path']} ({_ago(f['age'])} old)", file=sys.stderr)
        return _ask(a, "Remove them?")

    result = broker.clean(a.path, leases=a.leases, marks=a.marks, dry_run=a.dry_run, confirm=confirm)
    _report_removed(a, result, broker.CLEANED)


def _score(a) -> None:
    """``linecaster score``: a run's page records against a ground truth's, by a benchmark: score records
    (Parquet) and one evidence record."""
    from pathlib import Path

    from .catalog import yamlio
    from .catalog.registry import rendering_policy
    from .scoring.benchmark import read_benchmark
    from .scoring.evidence import evidence, write_evidence
    from .scoring.run import score_run, write_scores

    bench = read_benchmark(yamlio.read(a.benchmark))
    pages = Path(a.run) / "pages" if (Path(a.run) / "pages").is_dir() else Path(a.run)
    result = score_run(pages, a.truth, bench, transcription=a.transcription, policy=rendering_policy(bench.policy))
    out = Path(a.out) if a.out else Path(a.run) / "scores"
    write_scores(result["records"], out / "scores.parquet")
    ev = evidence(result, bench, a.run, preset=a.preset, context=a.context)
    write_evidence(ev, out / "evidence.yaml")
    for name, m in sorted(result["rates"].items()):
        lo, hi = m.get("lo"), m.get("hi")
        interval = f" [{lo:.4f}, {hi:.4f}]" if lo is not None else ""
        print(f"{name:32s} {m['value']:.4f}{interval}" if m["value"] is not None else f"{name:32s} -")
    for ln, missing_n in sorted(result["conventions"].items()):
        print(f"conventions: lane {ln} does not apply {', '.join(missing_n)}, which the ground truth does")
    print(f"pages {result['pages_scored']}, missing {result['missing']}, failed {result['failed']}; "
          f"{'eligible' if result['eligible'] else 'NOT eligible'}; {out}")


def _evidence(a) -> None:
    """``linecaster evidence check|compare``: evidence records validated, or put side by side."""
    from .catalog import yamlio
    from .catalog.schema import Evidence3, read_evidence

    records = []
    for path in a.files:
        try:
            records.append((path, read_evidence(yamlio.read(path))))
        except Exception as e:  # noqa: BLE001 - name the file
            sys.exit(f"{path}: {e}")
    if a.action == "check":
        for path, ev in records:
            print(f"{path}: {ev.schema_} {ev.subject} OK")
        return
    new = [(p, e) for p, e in records if isinstance(e, Evidence3)]
    if len(new) != len(records):
        sys.exit("compare: an evidence/1 record does not say how it was scored")
    base = new[0][1]
    apart = [p for p, e in new[1:] if not base.comparable(e)]
    if apart or not base.comparable(base):
        sys.exit(f"not scored like {new[0][0]} (benchmark, policy, output strategy, lanes, unit or word metrics differ, or a "
                 f"record from before 0.10 names no hashes): {', '.join(apart) or new[0][0]}")
    names = sorted({k for _, e in new for k in e.metrics})
    print("metric".ljust(32) + "".join(e.subject[:24].rjust(26) for _, e in new))
    for k in names:
        row = []
        for _, e in new:
            m = e.metrics.get(k)
            row.append(("-" if m is None or m.value is None else f"{m.value:.4f}").rjust(26))
        print(k.ljust(32) + "".join(row))


def _images(a) -> None:
    """``linecaster images compare``: a GPU decode against Pillow's, per image (JSON lines) and in sum."""
    import json as _json

    import fsspec

    from .images import accel
    from .images.transcode import compare_decoders

    if not accel.gpu_available():
        raise PipelineConfigError("images compare: no CUDA device or no nvImageCodec here "
                                  "(pip install 'linecaster[nvimgcodec]')")
    paths = list(a.files)
    if a.paths_file:
        with fsspec.open(a.paths_file, "rt") as f:
            paths += [line.strip() for line in f if line.strip()]
    worst, n, gpu, differing = 0, 0, 0, 0
    for path in paths:
        with fsspec.open(path, "rb") as f:
            data = f.read()
        try:
            r = compare_decoders(data, a.device)
        except Exception as e:  # noqa: BLE001 - an image that cannot be decoded: said, the others go on
            print(_json.dumps({"path": path, "error": f"{type(e).__name__}: {e}"}), flush=True)
            continue
        print(_json.dumps({"path": path, **r}), flush=True)
        n += 1
        gpu += r["gpu"]
        differing += r["max_abs"] > 0
        worst = max(worst, r["max_abs"])
    print(f"{n} images, {gpu} decoded on the GPU, {differing} with pixels that differ from Pillow's, "
          f"largest difference {worst} (of 255)", file=sys.stderr)


def _ask(a, question: str) -> bool:
    """``linecaster broker``'s confirmation: yes with ``--yes``, else the answer on a terminal; refused without one."""
    if a.yes:
        return True
    if not sys.stdin.isatty():
        print(f"linecaster broker {a.action}: refused (no terminal to confirm on); stop the runs first, or pass "
              f"--yes", file=sys.stderr)
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def _report_removed(a, result: dict, categories: tuple[str, ...]) -> None:
    if result["aborted"]:
        sys.exit(1)
    verb = "would remove" if result["dry_run"] else "removed"
    removed = result["removed"]
    for category in categories:
        for f in removed[category] if (a.verbose or a.dry_run) else []:
            print(f"{verb} {f['path']}" + (" (live)" if f["live"] else ""))
    print(f"{verb}: " + ", ".join(f"{len(removed[c])} {c}" for c in categories))


def _models(a) -> None:
    from .catalog.registry import catalog

    c = catalog()
    rows = [("preset", "step", "engine", "model", "license", "support")]
    for pid, (_, p) in sorted(c.presets.items()):
        if a.step and p.step != a.step:
            continue
        lic = c.model(p.model.id).license if p.model else "-"
        rows.append((p.ref, p.step, p.engine, p.model.id if p.model else "-", lic, p.support))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(x.ljust(w) for x, w in zip(r, widths)).rstrip())
    if c.recipes and not a.step:
        print("\nrecipe".ljust(1))
        for rid, (_, rc) in sorted(c.recipes.items()):
            print(f"{rc.ref}  {rc.pipeline}  " + " ".join(f"{k}={v}" for k, v in rc.presets.items()))


def _docs(a) -> None:
    from . import docs

    files = docs.generate(a.out, a.readme)
    for path in docs.write(files, a.out):
        print(path)


def _catalog(a) -> None:
    from .catalog import registry

    if a.action == "verify":
        try:
            problems = registry.Catalog().verify()
        except CatalogError as e:                   # a file that does not load: unreadable, or not its schema
            problems = [str(e)]
        print("\n".join(problems) or "catalog OK")
        sys.exit(1 if problems else 0)
    if a.action == "show":
        from .catalog import yamlio

        c = registry.Catalog()
        kind = "recipe" if registry.entry_id(a.ref) in c.recipes else "preset"
        r = c.resolve_recipe(a.ref) if kind == "recipe" else c.resolve(a.ref)
        print(yamlio.dump({kind: r.ref, "sha256": r.sha256, **r.content}))
    elif a.action == "index":
        for path in registry.Catalog().write_index():
            print(path)
    elif a.action == "schemas":
        from .catalog import schema

        for path in schema.write_schemas(*([a.out] if a.out else [])):
            print(path)
    elif a.action == "pin":
        from .catalog import pin

        if a.hf:
            path = pin.pin_hf(registry.CORE, a.ref, a.hf, a.revision)
        else:
            path = pin.pin_github(registry.CORE, a.ref, a.github, a.revision, a.file, tag=a.tag)
        print(path)


#: the pipeline ``linecaster page`` runs without --recipe or --pipeline
PAGE_PIPELINE = "transcribe_modular.v1"


def page_command(image: str, out: str, rest: list[str], pipeline: str | None = None) -> list[str]:
    """The pipeline script's command line for ``linecaster page``: the script of ``pipeline`` (a pipeline id), else
    of the recipe ``--recipe`` in ``rest`` names, else of ``PAGE_PIPELINE``, with ``--page IMAGE OUT``."""
    from .catalog import code

    if pipeline is None:
        ap = argparse.ArgumentParser(add_help=False)
        ap.add_argument("--recipe")
        known, _ = ap.parse_known_args(rest)
        if known.recipe:
            from .catalog.registry import catalog

            pipeline = catalog().resolve_recipe(known.recipe).content["pipeline"]
    pipeline = pipeline or PAGE_PIPELINE
    if code.REPO is None or not (code.REPO / "pipelines").is_dir():
        raise PipelineConfigError("linecaster page runs a pipeline script (pipelines/*.py): it needs the repository checkout")
    scripts = code.pipelines()
    if pipeline not in scripts:
        raise PipelineConfigError(f"no pipeline script for {pipeline} (pipelines/*.py: {', '.join(sorted(scripts))})")
    return ["uv", "run", "--script", str(scripts[pipeline].source), "--page", image, out, *rest]


def _page(a, rest: list[str]) -> None:
    import os

    cmd = page_command(a.image, a.out, rest, a.pipeline)
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}       # the script's own environment
    os.execvpe(cmd[0], cmd, env)


def _fractions(specs: list[str]) -> dict[str, float] | None:
    """``NAME:FRACTION`` options as named fractions, in order."""
    out: dict[str, float] = {}
    for spec in specs or ():
        name, sep, value = spec.rpartition(":")
        try:
            out[name] = float(value)
        except ValueError:
            name = ""
        if not sep or not name:
            raise PipelineConfigError(f"--split {spec!r}: NAME:FRACTION (test:0.2)")
    return out or None


def _truth_check(a) -> None:
    """``linecaster truth check``: what a ground truth's page records hold, per page and in total."""
    from pathlib import Path

    from .scoring.truth import check, render

    ids = set(Path(a.ids).read_text(encoding="utf-8").split()) if a.ids else None
    report = check(a.truth, a.transcription, ids)
    if a.json:
        Path(a.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(render(report))


def _truth_publish(a) -> None:
    """``linecaster truth publish``: a ground truth's page records as a Hub dataset (Parquet and a dataset card)."""
    from .scoring.publish import publish

    read_image = None
    if a.images is None and not a.no_images:
        from .blocks.conversion.images import read_uri

        read_image = read_uri
    got = publish(a.truth, a.out, a.transcription, images=a.images, read_image=read_image,
                  splits=_fractions(a.split), seed=a.seed, license=a.license, name=a.name, shard_pages=a.shard_pages)
    print(f"pages {got['pages']:,} (with an image {got['images']:,}); "
          + ", ".join(f"{s} {n:,}" for s, n in got["splits"].items()) + f"; {a.out}/README.md")


def _benchmark_init(a) -> None:
    """``linecaster benchmark init``: a benchmark definition from a ground truth's page records."""
    from .data.sample import SampleRule
    from .scoring.truth import benchmark, write_benchmark

    splits = _fractions(a.split)
    limits = (a.sample, a.sample_items, a.sample_per_item, a.per_stratum)
    rule = None
    if any(x is not None for x in limits) or splits or a.stratify:
        try:
            rule = SampleRule(pages=a.sample, items=a.sample_items, per_item=a.sample_per_item, seed=a.seed,
                              stratify=a.stratify, per_stratum=a.per_stratum, splits=splits,
                              split=(a.in_split or next(iter(splits))) if splits else None)
        except ValueError as e:
            raise PipelineConfigError(f"benchmark init: {e}") from None
    from pathlib import Path

    try:
        data, comments = benchmark(a.truth, a.id or Path(a.out).name.split(".")[0], a.transcription, rule,
                                   dataset=a.dataset, importer=a.importer)
    except ValueError as e:
        raise PipelineConfigError(f"benchmark init: {e}") from None
    write_benchmark(data, comments, a.out)
    s = data["supports"]
    print(f"{data['id']}: {len(data['pages']['ids']):,} pages ({data['pages']['sha256']}); supports roles "
          f"{', '.join(s['roles']) or 'none'}, boxes {s['boxes']}, reading order {s['reading_order']}, notes "
          f"{s['notes']}, continuations {s['continuations']}; {a.out}")


def _ground_truth_parsers(sub) -> None:
    """``linecaster truth check|publish`` and ``linecaster benchmark init``."""
    tr = sub.add_parser("truth", help="ground truths' page records: check what they hold (check), publish them as a "
                                      "Hugging Face dataset (publish) (docs/reference/evaluation.md)")
    tsub = tr.add_subparsers(dest="action", required=True)
    tc = tsub.add_parser("check", help="per page and in total: lines, boxes outside the image, reading order, "
                                       "conventions' coverage, illegible characters, languages, scripts, directions, "
                                       "duplicates, roles, tables, formulas")
    tc.add_argument("truth", help="the ground truth's page records (a folder: local or fsspec URI)")
    tc.add_argument("--transcription", default="ground_truth", help="the ground truth's transcription")
    tc.add_argument("--ids", help="a file of page ids (one per line): only these pages")
    tc.add_argument("--json", metavar="OUT", help="also write the report as JSON to OUT")
    tc.set_defaults(handler=_truth_check)
    tp = tsub.add_parser("publish", help="the page records as Hub-ready Parquet (a row per page: id, item, image, "
                                         "text, the page record) with a generated dataset card")
    tp.add_argument("truth", help="the ground truth's page records")
    tp.add_argument("out", help="the dataset's folder (data/*.parquet, README.md)")
    tp.add_argument("--transcription", default="ground_truth", help="the ground truth's transcription")
    tp.add_argument("--images", metavar="FOLDER", help="the page images: the file of each image's name, else of the "
                                                       "page id (default: read from the records' image addresses)")
    tp.add_argument("--no-images", action="store_true", help="no image column values")
    tp.add_argument("--split", action="append", default=[], metavar="NAME:FRACTION",
                    help="a split of the items (all pages of an item in one), e.g. test:0.2; repeatable; default: "
                         "every page in train")
    tp.add_argument("--seed", type=int, default=0, help="the seed of the splits")
    tp.add_argument("--license", help="the card's license, where the records record none (default: other)")
    tp.add_argument("--name", help="the card's title (default: OUT's name)")
    tp.add_argument("--shard-pages", type=int, default=1000, help="pages per Parquet file")
    tp.set_defaults(handler=_truth_publish)
    bm = sub.add_parser("benchmark", help="benchmark definitions: one from a ground truth's data (init)")
    bsub = bm.add_subparsers(dest="action", required=True)
    bi = bsub.add_parser("init", help="a linecaster.benchmark/2 definition: supports from the data, the page set "
                                      "with its hash (all pages, or a sample, stratified, of a split), lanes "
                                      "diplomatic and reading, a comment per script recorded")
    bi.add_argument("truth", help="the ground truth's page records")
    bi.add_argument("out", help="the definition's file (YAML)")
    bi.add_argument("--id", help="the benchmark's id (default: OUT's name)")
    bi.add_argument("--transcription", default="ground_truth", help="the ground truth's transcription")
    bi.add_argument("--dataset", metavar="REPO@REVISION", help="the dataset (default: the one its sources name)")
    bi.add_argument("--importer", help="what made the page records (default: the import annotator's preset or "
                                       "engine, else the source's format)")
    bi.add_argument("--sample", type=int, metavar="N", help="at most N pages (stratified: shared in proportion)")
    bi.add_argument("--sample-items", type=int, metavar="M", help="at most M items")
    bi.add_argument("--sample-per-item", type=int, metavar="K", help="at most K pages of each item")
    bi.add_argument("--seed", "--sample-seed", type=int, default=0, help="the sample's and splits' seed")
    bi.add_argument("--stratify", metavar="SCHEME", help="strata by a page value: a scheme recorded on the page "
                                                         "(language, script, direction, ...), metadata.KEY or "
                                                         "source.FIELD")
    bi.add_argument("--per-stratum", type=int, metavar="K", help="K pages of each stratum")
    bi.add_argument("--split", action="append", default=[], metavar="NAME:FRACTION",
                    help="splits of the items, e.g. test:0.2 and train:0.8; the benchmark takes --in-split's pages")
    bi.add_argument("--in-split", metavar="NAME", help="the split the benchmark takes (default: the first named)")
    bi.set_defaults(handler=_benchmark_init)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="linecaster")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="host engines over HTTP (for blocks with a Served backend)")
    s.add_argument("--config", help="JSON file: {\"models\": [{\"name\", \"preset\", \"overrides\"} or "
                                    "{\"name\", \"spec\", \"kwargs\"}, optional \"max_queue\"]}")
    s.add_argument("--preset", action="append", default=[], metavar="NAME=ID[@EDITION]",
                   help="host a catalog preset under NAME")
    s.add_argument("--model", action="append", default=[], metavar="NAME=module:Class")
    s.add_argument("--kwargs", action="append", default=[], metavar="NAME=JSON")
    s.add_argument("--host", default="127.0.0.1", help="bind address (default loopback only)")
    s.add_argument("--port", type=int, default=8100)
    s.add_argument("--max-queue", type=int, default=64, help="requests a model accepts before answering 429")
    s.add_argument("--decode-workers", type=int, default=4)
    s.add_argument("--decoded-gb", type=float, default=4.0, metavar="GB",
                   help="decoded page images the server keeps, so the steps of one page (layout, lines, recognition) "
                        "decode it once (default 4 GB)")
    s.add_argument("--traces", default=None, metavar="FILE",
                   help="write the spans of traced requests to FILE (OTLP JSON lines, .jsonl.gz; default "
                        "LINECASTER_TRACES, which a pipeline task sets for the server it starts)")
    m = sub.add_parser("models", help="the catalog's presets")
    m.add_argument("--step", default=None)
    c = sub.add_parser("catalog", help="pin models, verify and index the catalog (docs/reference/catalog.md)")
    c.add_argument("action", choices=["verify", "show", "index", "pin", "schemas"])
    c.add_argument("ref", nargs="?", help="show: a preset or recipe id; pin: a model id")
    c.add_argument("--hf", help="pin: Hugging Face repo")
    c.add_argument("--github", help="pin: GitHub owner/name")
    c.add_argument("--revision", help="pin: commit, tag or branch (Hugging Face) / full commit (GitHub)")
    c.add_argument("--tag", help="pin (GitHub): the tag or branch the commit was taken from")
    c.add_argument("--file", action="append", default=[], help="pin (GitHub): a file to hash; repeatable")
    c.add_argument("--out", help="schemas: output folder (default: the package's schemas/)")
    d = sub.add_parser("docs", help="write the generated docs (not in git; before building the site): the catalog's "
                                    "and the blocks' pages, the site's index and changelog, and llms.txt")
    d.add_argument("--out", default="docs", help="the docs folder (default docs)")
    d.add_argument("--readme", default="README.md", help="the README the site's index is made from (default "
                                                         "README.md)")
    p = sub.add_parser("page", help="run a pipeline script's blocks on one page image in this process, without an "
                                    "executor; the pipeline's options follow (--recipe R, --lines ..., --files DIR)")
    p.add_argument("image", help="the page image")
    p.add_argument("out", help="output folder: the page record in OUT/pages, files where the options say")
    p.add_argument("--pipeline", help=f"the pipeline id (default: the recipe's, else {PAGE_PIPELINE})")
    sub.add_parser("sample", add_help=False,
                   help="the sample of an input without a run (--sample N, --sample-per-item K, --sample-items M, "
                        "--sample-seed S, and the pipelines' input options): OUT/sample.parquet, as a run writes it")
    t = sub.add_parser("traces", help="what a run's traces say: per block the time per page (p50/p90/p99), the split "
                                      "of served requests, gaps, the slowest pages, per task the warm-up")
    t.add_argument("out", help="the run folder (its traces/)")
    t.add_argument("--by", choices=["block", "preset", "task"], default="block",
                   help="group the time per page by block, preset edition or task")
    t.add_argument("--slowest", type=int, default=10, metavar="N", help="the N slowest traced pages")
    t.add_argument("--json", action="store_true", help="the report as JSON")
    sc = sub.add_parser("score", help="score a run's page records against a ground truth's, by a benchmark: score "
                                      "records and an evidence record (docs/reference/evaluation.md)")
    sc.add_argument("run", help="the run folder (OUT) or its pages/")
    sc.add_argument("truth", help="the ground truth's page records")
    sc.add_argument("--benchmark", required=True, help="the benchmark definition (linecaster.benchmark/2 YAML; /1 is read)")
    sc.add_argument("--transcription", default="ocr_new", help="the run's transcription scored")
    sc.add_argument("--preset", help="the preset measured (its id), when the run follows no recipe")
    sc.add_argument("--context", help="for a preset measured inside a pipeline: the rest of it")
    sc.add_argument("--out", help="where scores.parquet and evidence.yaml go; default RUN/scores")
    ex = sub.add_parser("export", help="a ground truth and a run in an external benchmark's formats, for its own "
                                       "evaluation to score (omnidocbench)")
    ex.add_argument("format", choices=["omnidocbench"], help="the benchmark's formats")
    ex.add_argument("out", help="the folder the export goes to (its README says how to score it)")
    ex.add_argument("--truth", required=True, help="the ground truth's page records (a folder: local or fsspec URI)")
    ex.add_argument("--pages", required=True, help="the run's page records")
    ex.add_argument("--transcription", default="ocr_new", help="the run's transcription")
    ex.add_argument("--truth-transcription", default="ground_truth", help="the ground truth's transcription")
    ex.add_argument("--ids", help="a file of page ids (one per line): only these pages")
    ex.add_argument("--tables", choices=["data", "all"], default="data",
                    help="which tables are tables, on both sides: data (printed as tables; linecaster.scoring.tables) "
                         "or all")
    ex.add_argument("--strategy", help="an output strategy applied to every text of both sides (e.g. nfc)")
    _ground_truth_parsers(sub)
    ev = sub.add_parser("evidence", help="evidence records: check (validate) or compare (side by side, only those "
                                         "scored the same way)")
    ev.add_argument("action", choices=["check", "compare"])
    ev.add_argument("files", nargs="+", help="evidence record files (YAML)")
    i = sub.add_parser("images", help="image codecs: how a GPU decode compares with Pillow's (compare)")
    isub = i.add_subparsers(dest="action", required=True)
    ic = isub.add_parser("compare", help="decode each image on the GPU and with Pillow, the same colour handling after "
                                         "both, and say how the pixels differ (one JSON line each, a sum at the end)")
    ic.add_argument("files", nargs="*", help="image files, any fsspec path")
    ic.add_argument("--paths-file", help="a file listing image files, one per line")
    ic.add_argument("--device", type=int, default=0, help="the CUDA device")
    b = sub.add_parser("broker", help="what a broker's folder holds (status); remove its expired files or, after "
                                      "a hard kill, all leases (clean); reset it (purge) (docs/reference/broker.md)")
    bsub = b.add_subparsers(dest="action", required=True)
    bs = bsub.add_parser("status", help="the workers, slots, and per kind the resources held, free, blocked, broken")
    bs.add_argument("path", help="the broker's folder, any fsspec path (e.g. OUT/logs/broker, s3://bucket/broker)")
    bs.add_argument("--json", action="store_true", help="one JSON object with the same content")
    bc = bsub.add_parser("clean", help="remove expired heartbeats, leases and marks (safe while a run goes on); "
                                       "--leases after a hard kill")
    bc.add_argument("path", help="the broker's folder, any fsspec path")
    bc.add_argument("--leases", action="store_true",
                    help="also remove every heartbeat, slot lease and resource lease, live or not (after a hard "
                         "kill; only when no run uses the broker); marks are kept")
    bc.add_argument("--marks", action="store_true", help="also remove every mark, live or not (blocked proxies are "
                                                         "tried again at once)")
    bc.add_argument("--dry-run", action="store_true", help="list what would be removed; remove nothing")
    bc.add_argument("--yes", action="store_true", help="remove live files without asking")
    bc.add_argument("-v", "--verbose", action="store_true", help="list each removed file")
    bp = bsub.add_parser("purge", help="reset the broker: remove every file of its layout, broker.json among them, "
                                       "live or not (asks first)")
    bp.add_argument("path", help="the broker's folder, any fsspec path")
    bp.add_argument("--dry-run", action="store_true", help="list what would be removed; remove nothing")
    bp.add_argument("--yes", action="store_true", help="remove without asking")
    bp.add_argument("-v", "--verbose", action="store_true", help="list each removed file")
    a, rest = ap.parse_known_args(argv)
    if rest and a.command not in ("page", "sample"):
        ap.error(f"unrecognized arguments: {' '.join(rest)}")
    try:
        if a.command == "page":
            _page(a, rest)
        elif a.command == "sample":
            from .runtime import run

            run.sample(rest)
        elif a.command == "serve":
            _serve(a)
        elif a.command == "models":
            _models(a)
        elif a.command == "catalog":
            _catalog(a)
        elif a.command == "docs":
            _docs(a)
        elif a.command == "traces":
            _traces(a)
        elif a.command == "broker":
            _broker(a)
        elif a.command == "images":
            _images(a)
        elif a.command == "score":
            _score(a)
        elif a.command == "evidence":
            _evidence(a)
        elif a.command == "export":
            _export(a)
        elif a.command in ("truth", "benchmark"):
            a.handler(a)
    except LinecasterError as e:            # the exit code (2: a pipeline that cannot run)
        print(e, file=sys.stderr)
        sys.exit(exit_code(e))



def _export(a) -> None:
    from pathlib import Path

    from .formats.omnidocbench import export
    from .scoring.run import read_truth, truth_ids

    ids = set(Path(a.ids).read_text().split()) if a.ids else truth_ids(a.truth)
    counts = export(a.out, read_truth(a.truth, ids), read_truth(a.pages, ids), a.transcription, a.truth_transcription,
                    a.tables, a.strategy)
    print(f"pages {counts['pages']:,}, missing {counts['missing']:,}, failed {counts['failed']:,}; {a.out}/README.md "
          f"says how OmniDocBench scores it")


if __name__ == "__main__":
    main()
