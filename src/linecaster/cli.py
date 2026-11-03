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
                hosted.append(Hosted(m["name"], m["spec"], m.get("kwargs", {}), m.get("max_queue", a.max_queue),
                                     m.get("replicas", 1)))
    kwargs = dict(kv.split("=", 1) for kv in a.kwargs)
    for m in a.model:
        name, spec = m.split("=", 1)
        hosted.append(Hosted(name, spec, json.loads(kwargs.get(name, "{}")), a.max_queue))
    for kv in a.replicas:
        name, n = kv.split("=", 1)
        match = [h for h in hosted if h.name == name]
        if not match:
            sys.exit(f"linecaster serve: --replicas for unknown model {name!r}")
        match[0].replicas = int(n)
    if not hosted:
        sys.exit("linecaster serve: no models (use --config or --model NAME=module:Class)")
    serve(hosted, a.host, a.port, a.decode_workers)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="linecaster")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="host engine models over HTTP (for blocks with a Served backend)")
    s.add_argument("--config", help="JSON file: {\"models\": [{\"name\", \"spec\", \"kwargs\", \"max_queue\", \"replicas\"}]}")
    s.add_argument("--model", action="append", default=[], metavar="NAME=module:Class")
    s.add_argument("--kwargs", action="append", default=[], metavar="NAME=JSON")
    s.add_argument("--replicas", action="append", default=[], metavar="NAME=N",
                   help="copies of a model on the device, each serving one request at a time (default 1)")
    s.add_argument("--host", default="127.0.0.1", help="bind address (default loopback only)")
    s.add_argument("--port", type=int, default=8100)
    s.add_argument("--max-queue", type=int, default=64, help="requests a model accepts before answering 429")
    s.add_argument("--decode-workers", type=int, default=4)
    a = ap.parse_args(argv)
    if a.command == "serve":
        _serve(a)


if __name__ == "__main__":
    main()
