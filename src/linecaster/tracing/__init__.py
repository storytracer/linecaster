"""Tracing with OpenTelemetry, always on (``docs/reference/tracing.md``).

Per task a ``TracerProvider`` (``task_provider``): its resource names the service (``linecaster``), its version, the
run, the task, the host and the GPU; its spans go to ``<run folder>/traces/<rank>.jsonl.gz`` (OTLP JSON lines,
``JsonlFileExporter``) and, when the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` (or ``..._TRACES_ENDPOINT``) is set, to
that OTLP/HTTP endpoint. Nothing else is sent anywhere.

The builder installs a ``Tracing`` observer in every stage (``linecaster.runtime.builder.build``); it opens the
provider in ``on_task_start`` and flushes and shuts it down in ``on_task_end``, also when the task fails. It keeps
no state between tasks, and pickles without any (``__getstate__``), so it works on every executor.

* **Task spans**, always: ``linecaster.task`` (the task), ``linecaster.warm_up`` (per block that loads something),
  ``linecaster.server.start`` (a server block's warm-up), ``linecaster.reader.file`` (a file a reader read),
  ``linecaster.writer.flush`` (a writer closing its files).
* **Unit traces**: the reader's boundary gives every page a trace (``doc.metadata["trace"]["traceparent"]``, W3C);
  its root ``linecaster.page`` has one ``linecaster.block`` per block, ``linecaster.request.prepare`` and
  ``linecaster.request`` inside served blocks (the server continues the trace: ``linecaster.serve.*``), and
  ``linecaster.http.fetch`` for what the reader fetched. Items made by a binder get ``linecaster.item`` traces.
  Every span has its parent set explicitly from the unit's context, never from "the current span": pages are
  interleaved in the stream.
* **Sampling** by unit id (``sampled``): a fixed share ``sample`` (``--trace-sample``, default 0.01) is traced,
  the same pages on every rerun; the spans of the others are recorded and held per page (``PageBuffer``) and
  exported only if the page failed in the stage. A sampled page's record carries ``metadata.trace_id``.
* **Attributes** are identifiers and numbers under ``linecaster.*`` (``ATTRIBUTES``), never text or images.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time

from opentelemetry import trace as trace_api
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
from opentelemetry.sdk.trace.sampling import Decision, Sampler, SamplingResult
from opentelemetry.trace import SpanContext, StatusCode, TraceFlags
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from ..runtime.observers import Observer
from .export import JsonlFileExporter, PageBuffer

#: where a document carries its trace context: ``doc.metadata["trace"] = {"traceparent": ...}``
TRACE_KEY = "trace"
#: the share of pages traced by default (``--trace-sample``)
DEFAULT_SAMPLE = 0.01
#: the instrumentation scope of linecaster's spans
SCOPE = "linecaster"
#: a server started in a task writes its spans to this file (set by the task for ``linecaster serve``)
TRACES_ENV = "LINECASTER_TRACES"
#: the run and the task, for a server's resource
RUN_ENV, TASK_ENV = "LINECASTER_RUN", "LINECASTER_TASK"

#: the attribute names (all under ``linecaster.``); values are identifiers and numbers, never content
ATTRIBUTES = ("block", "block.name", "block.family", "unit", "page.id", "item.id", "preset", "edition", "engine",
              "model", "backend", "server", "step", "lines", "regions", "words", "tokens.prompt",
              "tokens.completion", "finish_reason", "error.type", "region", "file", "pages", "seconds.own",
              "http.host", "http.status", "http.attempts", "http.retries", "http.wait_seconds", "task", "stage")

PAGE_ID, ITEM_ID = "linecaster.page.id", "linecaster.item.id"


def sampled(unit_id: str, rate: float) -> bool:
    """Whether the unit ``unit_id`` is in the sample of share ``rate``: by a hash of the id, so the same units on
    every rerun and every machine (0: none, 1: all)."""
    if rate >= 1:
        return True
    if rate <= 0:
        return False
    h = int.from_bytes(hashlib.blake2b(unit_id.encode("utf-8"), digest_size=8).digest(), "big")
    return h < rate * 2**64


def otlp_configured(env=None) -> bool:
    """Whether the standard variables ask for an OTLP export (``OTEL_EXPORTER_OTLP_ENDPOINT`` or
    ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT``, unless ``OTEL_TRACES_EXPORTER=none``)."""
    env = os.environ if env is None else env
    if (env.get("OTEL_TRACES_EXPORTER") or "").strip().lower() == "none":
        return False
    return bool(env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or env.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


def otlp_traces_endpoint(env=None) -> str | None:
    """The OTLP/HTTP traces URL the variables name (the signal's own, or the base with ``/v1/traces``)."""
    env = os.environ if env is None else env
    if not otlp_configured(env):
        return None
    if env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        return env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"]
    return env["OTEL_EXPORTER_OTLP_ENDPOINT"].rstrip("/") + "/v1/traces"


class UnitSampler(Sampler):
    """A span with a parent follows the parent's decision (sampled, or recorded only: held by the ``PageBuffer``);
    a unit root (with ``linecaster.page.id`` or ``linecaster.item.id``) is sampled by ``sampled(id, rate)``; any other
    root (task spans) is always sampled."""

    def __init__(self, rate: float):
        self.rate = rate

    def should_sample(self, parent_context, trace_id, name, kind=None, attributes=None, links=None,
                      trace_state=None) -> SamplingResult:
        parent = trace_api.get_current_span(parent_context).get_span_context()
        if parent.is_valid:
            keep = parent.trace_flags.sampled
        else:
            unit = (attributes or {}).get(PAGE_ID) or (attributes or {}).get(ITEM_ID)
            keep = True if unit is None else sampled(str(unit), self.rate)
        return SamplingResult(Decision.RECORD_AND_SAMPLE if keep else Decision.RECORD_ONLY, attributes,
                              parent.trace_state if parent.is_valid else trace_state)

    def get_description(self) -> str:
        return f"UnitSampler({self.rate})"


def gpus() -> list[str]:
    """The NVIDIA GPUs' model names, from the driver's ``/proc`` files, else (a driver that names none there, as on
    the GB10) from ``nvidia-smi``; none without the driver."""
    import glob

    out = []
    for path in sorted(glob.glob("/proc/driver/nvidia/gpus/*/information")):
        try:
            with open(path) as f:
                for line in f:
                    if line.startswith("Model:"):
                        out.append(line.split(":", 1)[1].strip())
        except OSError:
            continue
    if out and all(name in ("", "Unknown") for name in out):
        import subprocess

        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                               text=True, timeout=10, check=False)
            named = [x.strip() for x in r.stdout.splitlines() if x.strip()]
            out = named or out
        except (OSError, subprocess.SubprocessError):
            pass
    return out


def resource(process: str = "pipeline", run: str | None = None, task: int | None = None,
             world_size: int | None = None, stage: str | None = None) -> Resource:
    """The resource of a task's spans: ``service.name`` (``linecaster``), ``service.version``, ``host.name``,
    ``linecaster.process`` (``pipeline`` or ``serve``), ``linecaster.run``, ``linecaster.task``,
    ``linecaster.tasks``, ``linecaster.stage`` and ``linecaster.gpu`` (when known). ``OTEL_RESOURCE_ATTRIBUTES``
    adds to them."""
    import socket

    from .. import __version__

    attrs = {"service.name": "linecaster", "service.version": __version__, "host.name": socket.gethostname(),
             "linecaster.process": process}
    for key, value in (("linecaster.run", run), ("linecaster.task", task), ("linecaster.tasks", world_size),
                       ("linecaster.stage", stage)):
        if value is not None:
            attrs[key] = value
    found = gpus()
    if found:
        attrs["linecaster.gpu"] = found[0] if len(set(found)) == 1 else ", ".join(found)
        attrs["linecaster.gpus"] = len(found)
    return Resource.create(attrs)


class UnitIds(RandomIdGenerator):
    """Trace ids of units derived from the run and the unit's id (``for_unit``), so a rerun of a run gives its
    sampled pages the same ``trace_id`` in their page records; span ids and other traces' ids stay random."""

    def __init__(self, run: str | None):
        self.run = run or ""
        self._next = threading.local()

    def for_unit(self, unit_id: str) -> None:
        """The next trace id this thread asks for is ``unit_id``'s."""
        digest = hashlib.blake2b(f"{self.run}/{unit_id}".encode(), digest_size=16).digest()
        self._next.trace_id = int.from_bytes(digest, "big") or 1

    def generate_trace_id(self) -> int:
        trace_id = getattr(self._next, "trace_id", None)
        if trace_id is None:
            return super().generate_trace_id()
        self._next.trace_id = None
        return trace_id


def task_provider(res: Resource, sampler: Sampler | None = None, path: str | None = None,
                  otlp: bool | None = None, ids: UnitIds | None = None) -> tuple[TracerProvider, PageBuffer]:
    """A provider whose spans go through a ``PageBuffer`` to the file ``path`` (OTLP JSON lines; none without a
    path) and, with ``otlp`` (default: ``otlp_configured()``), to the OTLP/HTTP endpoint of the ``OTEL_*``
    variables. Shut it down (``provider.shutdown()``) to flush and close the file."""
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    inner = []
    if path:
        inner.append(BatchSpanProcessor(JsonlFileExporter(path), max_queue_size=2**16, schedule_delay_millis=2000,
                                        max_export_batch_size=1024))
    if otlp_configured() if otlp is None else otlp:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        inner.append(BatchSpanProcessor(OTLPSpanExporter(), max_queue_size=2**16))
    buffer = PageBuffer(inner)
    provider = TracerProvider(sampler=sampler or UnitSampler(1.0), resource=res, shutdown_on_exit=False,
                              **({"id_generator": ids} if ids is not None else {}))
    provider.add_span_processor(buffer)
    return provider, buffer


_PROPAGATOR = TraceContextTextMapPropagator()


def traceparent(ctx: SpanContext) -> str:
    """The W3C ``traceparent`` of a span context."""
    return f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-{int(ctx.trace_flags):02x}"


def context_of(value: str | None):
    """The OpenTelemetry context of a ``traceparent`` (an empty context for ``None`` or a malformed one)."""
    return _PROPAGATOR.extract({"traceparent": value} if value else {})


def trace_file(run_folder: str, rank: int, stage: str | None = None, suffix: str = "") -> str:
    """``<run_folder>/traces[/<stage>]/<rank>[suffix].jsonl.gz`` (rank as five digits, like datatrove's logs)."""
    folder = f"{run_folder.rstrip('/')}/traces" + (f"/{stage}" if stage else "")
    return f"{folder}/{rank:05d}{suffix}.jsonl.gz"


def _ns() -> int:
    return time.time_ns()


# ------------------------------------------------------------------------------------------------ the observer

def _family(block) -> str:
    parts = type(block).__module__.split(".")
    if len(parts) > 2 and parts[0] == "linecaster" and parts[1] == "blocks":
        return parts[2]
    return parts[0]


def block_attributes(block) -> dict:
    """The identifying attributes of a block's spans: class, name, family, unit; a model block's step, preset and
    edition, engine, model, backend and server."""
    from ..blocks.base.contract import contract_of

    attrs = {"linecaster.block": type(block).__name__, "linecaster.block.family": _family(block)}
    name = getattr(block, "name", None)
    if isinstance(name, str) and name:
        attrs["linecaster.block.name"] = name
    try:
        attrs["linecaster.unit"] = contract_of(block).unit
    except Exception:  # noqa: BLE001 - a block whose contract cannot be computed here
        pass
    step = getattr(block, "step", None)
    if isinstance(step, str) and step != "model":
        attrs["linecaster.step"] = step
    backend = getattr(block, "backend", None)
    spec = getattr(block, "spec", None) or getattr(backend, "adapter", None)      # a chat preset's adapter
    preset = getattr(spec, "preset", None) or getattr(backend, "preset", None)
    if isinstance(preset, str):
        attrs["linecaster.preset"] = preset.split("@", 1)[0]
        if "@" in preset:
            attrs["linecaster.edition"] = preset.split("@", 1)[1]
    if backend is not None and hasattr(backend, "served"):
        attrs["linecaster.backend"] = "served" if backend.served else "in-process"
        engine = getattr(backend, "engine", None) if backend.served else getattr(backend, "spec", None)
        if isinstance(engine, str):
            attrs["linecaster.engine"] = engine
        if backend.served:
            attrs["linecaster.server"] = backend.endpoint
            attrs["linecaster.model"] = backend.model
    if spec is not None and isinstance(getattr(spec, "model", None), str):
        attrs["linecaster.model"] = spec.model
    return attrs


def server_attributes(block) -> dict:
    """A server block's: what it serves (``linecaster serve``'s models, or the chat model) and its port."""
    attrs = {"linecaster.block": type(block).__name__, "linecaster.block.family": _family(block)}
    if hasattr(block, "models"):
        attrs["linecaster.server"] = "linecaster"
        attrs["linecaster.model"] = [m.get("name", "") for m in block.models]
        presets = [m["preset"] for m in block.models if m.get("preset")]
        if presets:
            attrs["linecaster.preset"] = presets
    elif hasattr(block, "spec"):
        attrs["linecaster.server"] = getattr(block, "server", "vllm")
        attrs["linecaster.model"] = getattr(block.spec, "model", "")
        if getattr(block.spec, "preset", None):
            attrs["linecaster.preset"] = block.spec.preset
    elif hasattr(block, "serve"):                     # ServiceServer: the service a page preset names
        attrs["linecaster.server"] = block.server
        attrs["linecaster.preset"] = block.ref
    if isinstance(getattr(block, "port", None), int):
        attrs["linecaster.port"] = block.port
    return attrs


def counts(doc, transcription: str | None) -> dict:
    """``linecaster.lines``, ``.regions`` and ``.words`` of a page's ``transcription`` (read from the page record's
    dict, nothing validated)."""
    page = doc.metadata.get("page")
    if not transcription or not isinstance(page, dict):
        return {}
    t = (page.get("transcriptions") or {}).get(transcription)
    if not isinstance(t, dict):
        return {}
    lines = t.get("lines") or []
    return {"linecaster.lines": len(lines), "linecaster.regions": len(t.get("regions") or []),
            "linecaster.words": sum(len(line.get("words") or ()) for line in lines if isinstance(line, dict))}


class _Unit:
    """A unit in flight: its id (never the document itself: a page a block drops must not stay in memory with its
    image), root span and context, whether it failed in this stage, its open spans."""

    __slots__ = ("id", "root", "context", "failed", "blocks", "requests")

    def __init__(self, doc, root, context):
        self.id, self.root, self.context, self.failed = str(doc.id), root, context, False
        self.blocks: dict[int, object] = {}             # id(block) -> its open linecaster.block span
        self.requests: dict[tuple, object] = {}         # (id(block), region) -> the open prepare or request span


class Tracing(Observer):
    """The observer that traces a stage's tasks (installed by the builder). ``run_folder``: where the spans go
    (``traces/``; none: only to OTLP, when configured); ``sample``: the share of units traced; ``run``: the run's
    name (default the run folder's); ``stage``: the stage's name when the run has several (its own folder of
    traces)."""

    def __init__(self, run_folder: str | None, sample: float = DEFAULT_SAMPLE, run: str | None = None,
                 stage: str | None = None):
        if not 0 <= sample <= 1:
            from ..errors import PipelineConfigError

            raise PipelineConfigError(f"--trace-sample is a share from 0 to 1, not {sample}")
        self.run_folder, self.sample, self.stage = run_folder, sample, stage
        self.run = run or os.environ.get(RUN_ENV) or (run_folder.rstrip("/").rsplit("/", 1)[-1] if run_folder else None)
        self._reset()

    def _reset(self) -> None:
        self.provider = self.buffer = self.tracer = self.ids = None
        self.task_span, self.task_context, self.rank, self.path = None, None, 0, None
        self._units: dict[int, _Unit] = {}
        self._inside: dict[int, int] = {}               # id(per-unit block) -> id() of the unit it works on
        self._attrs: dict[int, dict] = {}
        self._lock = threading.RLock()
        self._local = threading.local()

    def __getstate__(self):           # never pickle a provider, spans or open files
        return {"run_folder": self.run_folder, "sample": self.sample, "stage": self.stage, "run": self.run}

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._reset()

    # ------------------------------------------------------------------------------------------- the task
    def on_task_start(self, rank: int, world_size: int) -> None:
        self._reset()
        self.rank = rank
        self.path = trace_file(self.run_folder, rank, self.stage) if self.run_folder else None
        res = resource("pipeline", self.run, rank, world_size, self.stage)
        self.ids = UnitIds(self.run)
        self.provider, self.buffer = task_provider(res, UnitSampler(self.sample), self.path, ids=self.ids)
        self.tracer = self.provider.get_tracer(SCOPE)
        self.task_span = self.tracer.start_span("linecaster.task", context=Context(), attributes={
            "linecaster.task": rank, "linecaster.tasks": world_size, "linecaster.sample": self.sample,
            **({"linecaster.stage": self.stage} if self.stage else {})})
        self.task_context = trace_api.set_span_in_context(self.task_span)
        from ..runtime.logs import install_trace_ids

        install_trace_ids(self)

    def on_task_end(self, error=None) -> None:
        if self.provider is None:
            return
        from ..runtime.logs import remove_trace_ids

        try:
            with self._lock:
                left = list(self._units.values())
                self._units.clear()
            for u in left:                        # units that never reached the stage's end (dropped)
                self._end_unit(u, unfinished=True)
            if error is not None:
                self.task_span.set_status(StatusCode.ERROR, f"{type(error).__name__}: {error}"[:500])
                self.task_span.set_attribute("linecaster.error.type", type(error).__name__)
            self.task_span.set_attribute("linecaster.units.failed_exported", self.buffer.exported_failed)
            self.task_span.end()
        finally:
            remove_trace_ids(self)
            self.provider.shutdown()             # flushes, closes (uploads) the file
            self.provider = self.tracer = None

    def environment(self) -> dict[str, str]:
        """For a server a block starts in this task: the file its spans go to, the run and the task."""
        env = {TASK_ENV: str(self.rank)}
        if self.run:
            env[RUN_ENV] = self.run
        if self.run_folder:
            env[TRACES_ENV] = trace_file(self.run_folder, self.rank, self.stage, ".serve")
        return env

    def _child(self, name: str, parent_context, start: int | None = None, attributes: dict | None = None):
        return self.tracer.start_span(name, context=parent_context, start_time=start, attributes=attributes)

    def _attributes(self, block) -> dict:
        return self._info(block)[0]

    def _info(self, block) -> tuple[dict, bool]:
        """A block's attributes and whether it changes the stream's unit (a binder), computed once per task."""
        key = id(block)
        info = self._attrs.get(key)
        if info is None:
            info = self._attrs[key] = (block_attributes(block), _changes_unit(block))
        return info

    def on_warm_up(self, block, seconds: float) -> None:
        if self.tracer is None:
            return
        end = _ns()
        server = getattr(block, "role", None) == "server" or type(block).__name__ in (
            "ModelServer", "ChatModelServer", "ServiceServer")
        name = "linecaster.server.start" if server else "linecaster.warm_up"
        attrs = server_attributes(block) if server else dict(self._attributes(block))
        span = self._child(name, self.task_context, end - int(seconds * 1e9), attrs)
        span.end(end)

    def on_task_event(self, block, event: str, start_ns: int, end_ns: int, **attributes) -> None:
        if self.tracer is None:
            return
        name = {"file": "linecaster.reader.file", "flush": "linecaster.writer.flush"}.get(event, f"linecaster.{event}")
        attrs = {"linecaster.block": type(block).__name__,
                 **{f"linecaster.{k.replace('_', '.')}": v for k, v in attributes.items() if v is not None}}
        span = self._child(name, self.task_context, start_ns, attrs)
        span.end(end_ns)

    # ------------------------------------------------------------------------------------------- units
    def _unit(self, doc) -> _Unit:
        """The unit ``doc`` is, started now if it is new to this task: its root span (``linecaster.page`` or
        ``linecaster.item``), the fetch spans its reader recorded, its context on the document."""
        u = self._units.get(id(doc))
        if u is not None and u.id == str(doc.id):
            return u
        is_page = isinstance(doc.metadata.get("page"), dict)
        key = PAGE_ID if is_page else ITEM_ID
        carried = doc.metadata.get(TRACE_KEY) if isinstance(doc.metadata.get(TRACE_KEY), dict) else {}
        fetches = carried.get("fetch") or []
        now = _ns()
        start = min([now, *(int(f["start"]) for f in fetches if f.get("start"))])
        attrs = {key: str(doc.id), "linecaster.unit": "page" if is_page else "item"}
        if is_page and doc.metadata["page"].get("item_id"):
            attrs[ITEM_ID] = str(doc.metadata["page"]["item_id"])
        self.ids.for_unit(str(doc.id))
        root = self.tracer.start_span("linecaster.page" if is_page else "linecaster.item", context=Context(),
                                      start_time=start, attributes=attrs)
        ctx = root.get_span_context()
        u = _Unit(doc, root, trace_api.set_span_in_context(root))
        for f in fetches:
            self._fetch_span(u, f)
        doc.metadata[TRACE_KEY] = {"traceparent": traceparent(ctx)}
        if ctx.trace_flags.sampled and is_page:
            doc.metadata["page"].setdefault("metadata", {})["trace_id"] = f"{ctx.trace_id:032x}"
        self._units[id(doc)] = u
        return u

    def _dropped_before(self, block, doc) -> None:
        """A per-unit block works on one unit at a time: if the unit it had before ``doc`` never came out of it, the
        block dropped it (or passed on another object in its place), and its trace ends here, as unfinished (called
        with the lock held)."""
        if getattr(block, "shape", None) != "unit":
            return
        before = self._inside.get(id(block))
        self._inside[id(block)] = id(doc)
        u = self._units.get(before) if before is not None and before != id(doc) else None
        if u is not None and id(block) in u.blocks:
            del self._units[before]
            self._end_unit(u, unfinished=True)

    def _fetch_span(self, u: _Unit, f: dict) -> None:
        attrs = {f"linecaster.http.{k}": f[k] for k in ("host", "status", "attempts", "wait_seconds")
                 if f.get(k) is not None}
        if f.get("attempts"):
            attrs["linecaster.http.retries"] = max(0, int(f["attempts"]) - 1)
        if f.get("what"):
            attrs["linecaster.http.what"] = f["what"]
        span = self._child("linecaster.http.fetch", u.context, int(f["start"]), attrs)
        if f.get("error"):
            span.set_status(StatusCode.ERROR)
            span.set_attribute("linecaster.error.type", f["error"])
        span.end(int(f["end"]))

    def _end_unit(self, u: _Unit, unfinished: bool = False) -> None:
        now = _ns()
        for span in [*u.requests.values(), *u.blocks.values()]:
            span.end(now)
        u.requests.clear()
        u.blocks.clear()
        if unfinished:
            u.root.set_attribute("linecaster.unfinished", True)
        if u.failed:
            u.root.set_status(StatusCode.ERROR)
        u.root.end(now)

    def on_enter(self, block, doc) -> None:
        if self.tracer is None:
            return
        with self._lock:
            self._dropped_before(block, doc)
            u = self._unit(doc)
            attrs, changes_unit = self._info(block)
            if changes_unit:
                self._units.pop(id(doc), None)        # a page going into a binder: its trace ends here
                self._end_unit(u)
                return
            span = self._child("linecaster.block", u.context, None, {**attrs, PAGE_ID if "page" in doc.metadata
                                                                     else ITEM_ID: str(doc.id)})
            u.blocks[id(block)] = span
        if getattr(block, "shape", None) == "unit":
            self._local.span = span                  # for the logs of a per-unit block (same thread)

    def on_exit(self, block, doc, error=None) -> None:
        if self.tracer is None:
            return
        self._local.span = None
        with self._lock:
            u = self._unit(doc)
            span = u.blocks.pop(id(block), None)
            if error is not None:
                u.failed = True
        if span is not None:
            span.set_attributes(counts(doc, getattr(block, "transcription", None)))
            if error is not None:
                span.set_status(StatusCode.ERROR)
                span.set_attribute("linecaster.error.type", str(error.get("type") if isinstance(error, dict)
                                                                  else type(error).__name__))
            span.end()

    def on_leave(self, doc) -> None:
        if self.tracer is None:
            return
        with self._lock:
            u = self._units.pop(id(doc), None)
        if u is not None and u.id == str(doc.id):
            self._end_unit(u)

    def on_unit(self, block, doc, event: str, **attributes) -> None:
        if self.tracer is None:
            return
        region = attributes.get("region")
        key = (id(block), region)
        with self._lock:
            u = self._units.get(id(doc))
            if u is None or u.id != str(doc.id):
                return
            parent = u.blocks.get(id(block))
            parent_ctx = trace_api.set_span_in_context(parent) if parent is not None else u.context
            if event == "prepare":
                attrs = {"linecaster.region": region} if region is not None else None
                u.requests[key] = self._child("linecaster.request.prepare", parent_ctx, None, attrs)
            elif event == "request":
                prepare = u.requests.pop(key, None)
                if prepare is not None:
                    prepare.end()
                attrs = {"linecaster.region": region} if region is not None else {}
                span = u.requests[key] = self._child("linecaster.request", parent_ctx, None, attrs)
                carrier = attributes.get("carrier")
                if isinstance(carrier, dict):
                    carrier["traceparent"] = traceparent(span.get_span_context())
            elif event == "done":
                span = u.requests.pop(key, None)
                if span is None:
                    return
                for k, name in (("prompt_tokens", "linecaster.tokens.prompt"),
                                ("completion_tokens", "linecaster.tokens.completion"),
                                ("finish_reason", "linecaster.finish_reason")):
                    if attributes.get(k) is not None:
                        span.set_attribute(name, attributes[k])
                if attributes.get("error") is not None:
                    span.set_status(StatusCode.ERROR)
                    span.set_attribute("linecaster.error.type", "ServerError")
                span.end()

    # ------------------------------------------------------------------------------------------- logs
    def log_ids(self, record) -> tuple[int, int] | None:
        """The trace and span a log record belongs to: the page it names (``page_id``), else the block span of the
        per-unit block running in this thread, else the task span."""
        page_id = record["extra"].get("page_id")
        if page_id is not None:
            with self._lock:
                for u in self._units.values():
                    if u.id == page_id:
                        c = u.root.get_span_context()
                        return c.trace_id, c.span_id
        span = getattr(self._local, "span", None) or self.task_span
        if span is None:
            return None
        c = span.get_span_context()
        return c.trace_id, c.span_id


def _changes_unit(block) -> bool:
    from ..blocks.base.contract import contract_of

    try:
        c = contract_of(block)
    except Exception:  # noqa: BLE001
        return False
    return c.unit_out is not None and c.unit_out != c.unit
