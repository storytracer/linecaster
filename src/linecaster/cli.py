"""The ``linecaster`` command."""
from __future__ import annotations

import argparse
import json
import sys


def _serve(a) -> None:
    from .serve import Hosted, serve

    hosted = []
    if a.config:
        with open(a.config) as f:
            for m in json.load(f)["models"]:
                hosted.append(Hosted(m["name"], m["spec"], m.get("kwargs", {}), m.get("max_queue", a.max_queue)))
    for kv in a.preset:
        from .catalog.registry import engine_spec

        name, ref = kv.split("=", 1)
        spec, kw, r = engine_spec(ref)
        hosted.append(Hosted(name, spec, kw, a.max_queue, preset=r.ref, preset_sha256=r.sha256))
    kwargs = dict(kv.split("=", 1) for kv in a.kwargs)
    for m in a.model:
        name, spec = m.split("=", 1)
        hosted.append(Hosted(name, spec, json.loads(kwargs.get(name, "{}")), a.max_queue))
    if not hosted:
        sys.exit("linecaster serve: no models (use --preset NAME=ID, --config or --model NAME=module:Class)")
    serve(hosted, a.host, a.port, a.decode_workers)


def _models(a) -> None:
    from .catalog.registry import catalog

    c = catalog()
    rows = [("preset", "step", "engine", "model", "licence", "support")]
    for pid, (_, p) in sorted(c.presets.items()):
        if a.step and p.step != a.step:
            continue
        lic = c.model(p.model.id).license if p.model else "-"
        rows.append((p.ref, p.step, p.engine.kind, p.model.id if p.model else "-", lic, p.support))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(x.ljust(w) for x, w in zip(r, widths)).rstrip())


def _catalog(a) -> None:
    from pathlib import Path

    from .catalog import registry

    if a.action == "verify":
        problems = registry.Catalog().verify()
        print("\n".join(problems) or "catalogue OK")
        sys.exit(1 if problems else 0)
    if a.action == "show":
        r = registry.catalog().resolve(a.ref)
        from .catalog import yamlio

        print(yamlio.dump({"preset": r.ref, "sha256": r.sha256, "released": r.released, **r.content}))
    elif a.action == "docs":
        from .catalog import docs

        for path in docs.write(registry.Catalog(), a.out if a.out != "schemas" else "docs/catalog",
                               readme=a.readme):
            print(path)
    elif a.action == "release":
        e = registry.Catalog().release(a.ref, commit=a.commit)
        print(f"{a.ref}: {e.sha256} (released {e.released})")
    elif a.action == "schema":
        from .catalog import schema as S

        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, model in (("model", S.ModelDoc), ("preset", S.PresetDoc), ("evidence", S.Evidence),
                            ("catalog-lock", S.Lock)):
            (out / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(by_alias=True), indent=1))
        print(f"schemas in {out}")
    elif a.action == "pin":
        from .catalog import pin

        directory = Path(a.dir) if a.dir else registry.CORE
        if a.hf:
            path = pin.pin_hf(directory, a.ref, a.hf, a.revision)
        else:
            path = pin.pin_github(directory, a.ref, a.github, a.revision, a.file, tag=a.tag)
        print(path)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="linecaster")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="host engine models over HTTP (for blocks with a Served backend)")
    s.add_argument("--config", help="JSON file: {\"models\": [{\"name\", \"spec\", \"kwargs\", \"max_queue\"}]}")
    s.add_argument("--preset", action="append", default=[], metavar="NAME=ID[@EDITION]",
                   help="host a catalogue preset under NAME")
    s.add_argument("--model", action="append", default=[], metavar="NAME=module:Class")
    s.add_argument("--kwargs", action="append", default=[], metavar="NAME=JSON")
    s.add_argument("--host", default="127.0.0.1", help="bind address (default loopback only)")
    s.add_argument("--port", type=int, default=8100)
    s.add_argument("--max-queue", type=int, default=64, help="requests a model accepts before answering 429")
    s.add_argument("--decode-workers", type=int, default=4)
    m = sub.add_parser("models", help="the catalogue's presets")
    m.add_argument("--step", default=None)
    c = sub.add_parser("catalog", help="pin models, release and verify presets (specs/catalog.md)")
    c.add_argument("action", choices=["verify", "show", "release", "pin", "schema", "docs"])
    c.add_argument("ref", nargs="?", help="preset id[@edition] (show, release) or model id (pin)")
    c.add_argument("--hf", help="pin: Hugging Face repo")
    c.add_argument("--github", help="pin: GitHub owner/name")
    c.add_argument("--revision", help="pin: commit, tag or branch (Hugging Face) / full commit (GitHub)")
    c.add_argument("--tag", help="pin (GitHub): the tag or branch the commit was taken from")
    c.add_argument("--file", action="append", default=[], help="pin (GitHub): a file to hash; repeatable")
    c.add_argument("--dir", help="pin: the catalogue directory (default linecaster's own)")
    c.add_argument("--commit", help="release: the linecaster commit")
    c.add_argument("--out", default="schemas", help="schema, docs: output folder (docs: default docs/catalog)")
    c.add_argument("--readme", help="docs: also rewrite this README's model tables between its catalog markers")
    a = ap.parse_args(argv)
    if a.command == "serve":
        _serve(a)
    elif a.command == "models":
        _models(a)
    elif a.command == "catalog":
        _catalog(a)


if __name__ == "__main__":
    main()
