"""How many tasks and workers a run gets (``allocate``): from its proxies, its rate limits, its CPUs and GPUs,
with the notes that say why (``rate_note``, ``workers_note``)."""
from __future__ import annotations

import argparse

from linecaster.execution.cpus import available_cpus
from linecaster.execution.options import OBJECT_STORAGE_WORKERS
from linecaster.execution.wiring import http


def has_engines(a: argparse.Namespace) -> bool:
    """Whether the pipeline runs engines (``main`` sets ``a.has_engines`` from the script's ``models``; unknown counts
    as yes, which keeps one task and every task at once)."""
    return getattr(a, "has_engines", True)


def rate_note(a: argparse.Namespace) -> str | None:
    """What a server sees from ``--rate-limit`` (per worker) and the workers running at once: ``rate limits per
    worker: 150/60, 3/1 · 2 workers → up to 300/min at a server``; with ``--proxies`` per proxy and the proxies in use
    (``rate limits per proxy: 150/60 · 100 proxies → up to 15,000/min at a server``; with fewer workers than proxies
    times their count per worker, ``· 2 of 100 proxies in use (1 proxy per worker)``); and the HTTP policy
    (``--http-policy``); None without either."""
    hosts = None
    if getattr(a, "http_policy", None):
        from linecaster.net.policy import HTTPPolicy

        hosts = "HTTP policy: " + HTTPPolicy(a.http_policy, http(a)).describe()
    if not getattr(a, "rate_limits", None):
        return hosts
    limits = ", ".join(f"{n}/{s:g}" for n, s in a.rate_limits)
    if count := getattr(a, "proxy_count", None):     # one worker per proxy at a time: the limits hold per proxy
        from linecaster.net.proxies import DEFAULT_PER_WORKER, describe_per_worker

        per_worker = _proxy_plan(a)[1].get(a.proxies, {}).get("per_worker", DEFAULT_PER_WORKER)
        workers = min(a.workers or a.tasks or 1, a.tasks or 1) if a.workers or a.tasks else None
        used = min(count, workers * per_worker) if workers and isinstance(per_worker, int) else count
        proxies = f"{count:,} prox{'ies' if count != 1 else 'y'}"
        if used < count:
            proxies = f"{used:,} of {proxies} in use ({describe_per_worker(per_worker)})"
        per_minute = min(n / s for n, s in a.rate_limits) * 60 * used
        note = f"rate limits per proxy: {limits} · {proxies} → up to {per_minute:,.0f}/min at a server"
        return note + (f" · {hosts}" if hosts else "")
    workers = min(a.workers or a.tasks or 1, a.tasks or 1)
    per_minute = min(n / s for n, s in a.rate_limits) * 60 * workers
    note = (f"rate limits per worker: {limits} · {workers} worker{'s' if workers != 1 else ''} → up to "
            f"{per_minute:,.0f}/min at a server")
    return note + (f" · {hosts}" if hosts else "")


def workers_note(a: argparse.Namespace) -> str | None:
    """Why the run has the workers it has, when ``allocate`` chose them from the proxies (``250 proxies available →
    250 workers, 1 proxy each``); None otherwise."""
    return getattr(a, "workers_note", None)


def run_notes(a: argparse.Namespace) -> list[str]:
    """The lines a run states before it starts: ``workers_note`` and ``rate_note``, those it has."""
    return [n for n in (workers_note(a), rate_note(a)) if n]


def _proxy_plan(a: argparse.Namespace) -> tuple[bool, dict[str, dict]]:
    """How the run's requests go out, for ``allocate``: whether a host with rate limits goes without proxies (its
    limits then hold per worker), and the proxy lists, file -> ``hosts`` (the hosts that use it; None: any host
    without an entry), ``per_worker`` (its ``proxies: {per_worker}``), ``broker`` (the folder) and ``run`` (what the
    heartbeats name as the run)."""
    base = http(a)
    if getattr(a, "http_policy", None):
        from linecaster.net.policy import HTTPPolicy

        policy = HTTPPolicy(a.http_policy, base)
        entries = [(None, policy.settings(None)), *((h, policy.settings(h)) for h in policy.hosts)]
    else:
        entries = [(None, base)]
    from linecaster.net.proxies import DEFAULT_PER_WORKER

    direct, lists = False, {}
    for host, s in entries:
        if s.get("proxy_file"):
            g = lists.setdefault(s["proxy_file"], {"hosts": set(),
                                                   "per_worker": s.get("per_worker", DEFAULT_PER_WORKER),
                                                   "broker": s.get("broker") or s.get("default_broker"),
                                                   "run": s.get("broker_run")})
            g["hosts"].add(host)
        elif s.get("rate_limits"):
            direct = True
    return direct, lists


def available_proxies(path: str, hosts: set, broker: str | None, run: str | None) -> dict:
    """The proxies of the file ``path`` a run can use now, from one listing of the broker
    (``linecaster.net.broker.survey_kind``): ``proxies`` (in the file), ``blocked`` (a live block or broken mark there
    for one of ``hosts``, any host when None is among them), ``held`` (leased by a live worker of another run than
    ``run``; the run's own earlier leases do not count against it), ``available`` (the rest). Without a broker yet
    (a first launch), or one that cannot be read (a warning), all are available."""
    from linecaster.net.broker import survey_kind
    from linecaster.net.http import read_proxies
    from linecaster.net.proxies import KIND, TURN, proxy_id

    ids = {proxy_id(p) for p in read_proxies(path)}
    survey = {"resources": {}, "runs": {}}
    if broker:
        try:
            survey = survey_kind(broker, KIND)
        except Exception as e:  # noqa: BLE001 - the workers are then counted from the file alone
            from loguru import logger

            logger.warning("broker {broker} not read for the workers: {error}; every proxy counts as available",
                           broker=broker, error=e)
    blocked = held = 0
    for pid in ids:
        r = survey["resources"].get(pid)
        if r is None:
            continue
        if (any(not s.startswith(TURN) for s in r.marks) if None in hosts
                else any(r.marked(h) is not None for h in hosts)):         # a hand-over of a turn is no block
            blocked += 1
        elif r.holder is not None and r.holder in survey["runs"] and survey["runs"][r.holder] != run:
            held += 1
    return {"proxies": len(ids), "blocked": blocked, "held": held, "available": len(ids) - blocked - held}


def on_object_storage(path: str | None) -> bool:
    """Whether ``path`` is on object storage: any fsspec protocol but a local one (``s3://``, ``gs://``, ``hf://``,
    ``az://``, ...; not a plain path, ``file://``, ``local://`` or ``memory://``).

    Args:
        path: a folder, any fsspec path; None counts as local.
    """
    from fsspec.core import split_protocol

    protocol = split_protocol(str(path or ""))[0]
    return protocol not in (None, "file", "local", "memory")


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'s' if n != 1 else ''}"


def _proxy_workers(a: argparse.Namespace, lists: dict[str, dict]) -> tuple[int, str]:
    """The workers the proxy lists allow and why. Per list: one per available proxy divided by its
    ``per_worker`` (``ceil(available / N)``), or, sharing them fairly (``share``), the available proxies and
    at most one per CPU; the fewest over the lists, at least one. Then at most one per task and, with OUT on object
    storage (``on_object_storage``), at most ``OBJECT_STORAGE_WORKERS``. The reason names the limits that decided."""
    import math

    from linecaster.net.proxies import SHARE, describe_per_worker

    best, why, each, shared = None, "", "", False
    for path, g in lists.items():
        counts = available_proxies(path, g["hosts"], g["broker"], g["run"])
        available = counts["available"]
        left = [f"{counts[k]:,} {what}" for k, what in (("blocked", "blocked or broken"),
                                                         ("held", "held by other runs")) if counts[k]]
        reason = (f"{available:,} prox{'ies' if available != 1 else 'y'} available"
                  + (f" ({counts['proxies']:,} in the list, {', '.join(left)})" if left else ""))
        share = g["per_worker"] == SHARE
        n = max(1, available if share else math.ceil(available / g["per_worker"]))
        if best is None or n < best:
            best, why, shared = n, reason, share
            each = ("a fair share each" if share else "1 proxy each" if g["per_worker"] == 1
                    else describe_per_worker(g["per_worker"]).replace("per worker", "each"))
    caps = [(a.tasks, _plural(a.tasks, "task"))]
    if shared:                                          # a fair share needs no worker per proxy: one per CPU at most
        cpus = available_cpus()
        caps.append((cpus, _plural(cpus, "CPU")))
    if on_object_storage(getattr(a, "out", None)):
        caps.append((OBJECT_STORAGE_WORKERS, "OUT on object storage"))
    workers = min(best, *(n for n, _ in caps))
    why += "".join(f", {text}" for n, text in caps if n == workers and n < best)
    return workers, f"{why} → {_plural(workers, 'worker')}, {each}"


def allocate(a: argparse.Namespace, pipeline: list) -> None:
    """``--tasks`` and ``--workers`` where the command line leaves them open. A pipeline without engines: the task
    count its reader suggests (``auto_tasks``, from the input; one if it has none), and as workers: with a proxy list
    for every host that has rate limits, from the proxies available (``available_proxies``: the proxies in the file
    less those blocked or broken for the run's hosts and those held by another run's live workers, from one listing
    of the broker at launch): sharing them fairly (``proxies: {per_worker: share}``, the default) one per available
    proxy and at most one per CPU; with ``per_worker`` 1 or N one per available proxy divided by N
    (``ceil(available / N)``), never capped by the CPUs (the workers mostly wait on the network); either way at most
    one per task and, with OUT on object storage, at most ``OBJECT_STORAGE_WORKERS``, the reason in
    ``workers_note``. A host with rate limits and no proxy list: one worker (one task keeps them busy,
    ``linecaster.net.http.prefetched``); one per CPU otherwise, and on Ray every task (Ray's reservations,
    ``--cpus-per-task``, decide how many run at once, not the CPUs of the machine the driver runs on). A pipeline with engines: one task, every task at once;
    on Ray ``RAY_TASKS_PER_GPU`` tasks per GPU of the cluster (at most the reader's ``auto_tasks``), so a task that
    holds slow pages does not hold the run up: a worker that is done takes the next one. A pipeline whose tasks start
    a VLM's server (``starts_vlm_server``) counts as one with engines, with one task per GPU on Ray (the server takes
    minutes to start, once a task). ``--page``: one of each. The proxy rule holds for local and Ray runs only: on HF Jobs each worker is a Job, so its
    count is never derived from a proxy list."""
    if getattr(a, "page", None):
        a.tasks, a.workers = 1, 1
        return
    vlm = starts_vlm_server(pipeline)
    engines = has_engines(a) or vlm
    if a.tasks is None:
        reader = next((b for b in pipeline if hasattr(b, "auto_tasks")), None)
        if engines and getattr(a, "on", "local") == "ray":
            gpus = ray_gpus(a)
            a.tasks = max(1, (1 if vlm else RAY_TASKS_PER_GPU) * gpus) if gpus else 1
            if reader is not None and a.tasks > 1:
                a.tasks = max(1, min(a.tasks, reader.auto_tasks()))
        else:
            a.tasks = reader.auto_tasks() if reader is not None and not engines else 1
    if a.workers is None:
        if engines:
            a.workers = a.tasks
            return
        direct, lists = _proxy_plan(a)
        if lists and not direct and getattr(a, "on", "local") in ("local", "ray"):   # not a Job per proxy on HF Jobs
            a.workers, a.workers_note = _proxy_workers(a, lists)
            return
        if direct or getattr(a, "rate_limits", None) or _policy_rate_limited(a):
            a.workers = 1
        elif getattr(a, "on", "local") == "ray":     # the cluster's reservations bound it, not the driver's CPUs
            a.workers = a.tasks
        else:
            a.workers = min(a.tasks, available_cpus())


#: a pipeline with engines on Ray: tasks per GPU of the cluster, so the work is spread evenly however its pages differ
RAY_TASKS_PER_GPU = 4


def starts_vlm_server(pipeline: list) -> bool:
    """Whether each task of the pipeline starts a VLM's server (``VLMServer``: vLLM or SGLang, minutes to
    start): such a pipeline runs models, as one with engines, and on Ray gets one task per GPU, not
    ``RAY_TASKS_PER_GPU``, so a GPU starts its server once."""
    return any(type(b).__name__ == "VLMServer" for b in pipeline)


def ray_gpus(a: argparse.Namespace) -> int:
    """The GPUs of the Ray cluster at ``--address`` (joined here, as the launch joins it), 0 if it cannot be read."""
    try:
        from linecaster.execution.run import connect_ray

        connect_ray(a.address, getattr(a, "script_path", None), getattr(a, "worker_env", "script"))
        import ray

        return int(ray.cluster_resources().get("GPU", 0))
    except Exception:  # noqa: BLE001 - the launch joins the cluster and says what is wrong
        return 0


def _policy_rate_limited(a: argparse.Namespace) -> bool:
    if not getattr(a, "http_policy", None):
        return False
    from linecaster.net.policy import HTTPPolicy

    return HTTPPolicy(a.http_policy).rate_limited()
