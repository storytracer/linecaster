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
                if m.get("preset"):        # a catalogue preset, with options over the preset's
                    from .catalog.registry import engine_spec

                    spec, kw, r = engine_spec(m["preset"])
                    hosted.append(Hosted(m["name"], spec, {**kw, **m.get("overrides", {})},
                                         m.get("max_queue", a.max_queue), preset=r.ref, preset_sha256=r.sha256))
                else:
                    hosted.append(Hosted(m["name"], m["spec"], m.get("kwargs", {}), m.get("max_queue", a.max_queue)))
    kwargs = dict(kv.split("=", 1) for kv in a.kwargs)
    for kv in a.preset:
        from .catalog.registry import engine_spec

        name, ref = kv.split("=", 1)
        spec, kw, r = engine_spec(ref)
        kw.update(json.loads(kwargs.pop(name, "{}")))          # overrides, merged over the preset's options
        hosted.append(Hosted(name, spec, kw, a.max_queue, preset=r.ref, preset_sha256=r.sha256))
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
        rows.append((p.ref, p.step, p.engine, p.model.id if p.model else "-", lic, p.support))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(x.ljust(w) for x, w in zip(r, widths)).rstrip())
    if c.recipes and not a.step:
        print("\nrecipe".ljust(1))
        for rid, (_, rc) in sorted(c.recipes.items()):
            print(f"{rc.ref}  {rc.pipeline}  " + " ".join(f"{k}={v}" for k, v in rc.presets.items()))


def _catalog(a) -> None:
    from .catalog import registry

    if a.action == "verify":
        try:
            problems = registry.Catalog().verify()
        except ValueError as e:                     # a file that does not load: unreadable, or not its schema
            problems = [str(e)]
        print("\n".join(problems) or "catalog OK")
        sys.exit(1 if problems else 0)
    if a.action == "show":
        from .catalog import yamlio

        c = registry.Catalog()
        kind = "recipe" if a.ref.split("@", 1)[0] in c.recipes else "preset"
        r = c.resolve_recipe(a.ref) if kind == "recipe" else c.resolve(a.ref)
        print(yamlio.dump({kind: r.ref, "sha256": r.sha256, "released": r.released, **r.content}))
    elif a.action == "docs":
        from .catalog import docs

        for path in docs.write(registry.Catalog(), a.out or "docs/catalog", readme=a.readme):
            print(path)
    elif a.action == "release":
        e = registry.Catalog().release(a.ref, commit=a.commit)
        print(f"{a.ref}: {e.sha256} (released {e.released})")
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


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="linecaster")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="host engine models over HTTP (for blocks with a Served backend)")
    s.add_argument("--config", help="JSON file: {\"models\": [{\"name\", \"preset\", \"overrides\"} or "
                                    "{\"name\", \"spec\", \"kwargs\"}, optional \"max_queue\"]}")
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
    c = sub.add_parser("catalog", help="pin models, release and verify presets and recipes (docs/reference/catalog.md)")
    c.add_argument("action", choices=["verify", "show", "release", "pin", "schemas", "docs"])
    c.add_argument("ref", nargs="?", help="preset or recipe id[@edition] (show, release) or model id (pin)")
    c.add_argument("--hf", help="pin: Hugging Face repo")
    c.add_argument("--github", help="pin: GitHub owner/name")
    c.add_argument("--revision", help="pin: commit, tag or branch (Hugging Face) / full commit (GitHub)")
    c.add_argument("--tag", help="pin (GitHub): the tag or branch the commit was taken from")
    c.add_argument("--file", action="append", default=[], help="pin (GitHub): a file to hash; repeatable")
    c.add_argument("--commit", help="release: the linecaster commit")
    c.add_argument("--out", help="schemas, docs: output folder (default: the package's schemas/, docs/catalog)")
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
