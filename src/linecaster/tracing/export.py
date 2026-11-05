"""Where spans go: a file of OTLP JSON lines per task (``JsonlFileExporter``), and the page buffer (``PageBuffer``)
that holds the spans of unsampled pages until each page is done, exporting them only if it failed.

The file follows OpenTelemetry's file exporter format: one ``ExportTraceServiceRequest`` per line in the OTLP JSON
encoding (``resourceSpans`` → ``scopeSpans`` → ``spans``; ids as hex, times as nanoseconds since the epoch in
strings), gzipped, through datatrove's ``DataFolder`` (any fsspec path, like the logs)."""
from __future__ import annotations

import json
import threading
from collections.abc import Sequence

from opentelemetry import trace as trace_api
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

#: the roots of unit traces: their spans are buffered unless the unit is sampled
UNIT_ROOTS = ("linecaster.page", "linecaster.item")


def _value(v) -> dict:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_value(x) for x in v]}}
    return {"stringValue": str(v)}


def _attributes(attrs) -> list[dict]:
    return [{"key": k, "value": _value(v)} for k, v in (attrs or {}).items()]


def _span(s: ReadableSpan) -> dict:
    ctx = s.context
    out = {"traceId": f"{ctx.trace_id:032x}", "spanId": f"{ctx.span_id:016x}", "flags": int(ctx.trace_flags),
           "name": s.name, "kind": int(s.kind.value) + 1,       # the SDK's INTERNAL is 0, OTLP's 1
           "startTimeUnixNano": str(s.start_time), "endTimeUnixNano": str(s.end_time),
           "attributes": _attributes(s.attributes)}
    if s.parent is not None:
        out["parentSpanId"] = f"{s.parent.span_id:016x}"
    if s.status.status_code is not StatusCode.UNSET:
        out["status"] = {"code": 1 if s.status.status_code is StatusCode.OK else 2}
        if s.status.description:
            out["status"]["message"] = s.status.description
    if s.events:
        out["events"] = [{"timeUnixNano": str(e.timestamp), "name": e.name, "attributes": _attributes(e.attributes)}
                         for e in s.events]
    return out


def encode(spans: Sequence[ReadableSpan]) -> dict:
    """``spans`` as one OTLP JSON ``ExportTraceServiceRequest``, grouped by resource and scope."""
    resources: dict[int, tuple] = {}
    for s in spans:
        key = id(s.resource)
        if key not in resources:
            resources[key] = (s.resource, {})
        scope = s.instrumentation_scope
        skey = (scope.name, scope.version) if scope else ("", None)
        resources[key][1].setdefault(skey, []).append(_span(s))
    out = []
    for resource, scopes in resources.values():
        out.append({"resource": {"attributes": _attributes(resource.attributes if resource else {})},
                    "scopeSpans": [{"scope": {"name": n, **({"version": v} if v else {})}, "spans": ss}
                                   for (n, v), ss in scopes.items()]})
    return {"resourceSpans": out}


class JsonlFileExporter(SpanExporter):
    """Writes every batch of spans as one line of OTLP JSON to ``path`` (``folder/name.jsonl.gz``, any fsspec
    folder), opened on the first batch and closed by ``shutdown()``: a remote file is uploaded then."""

    def __init__(self, path: str):
        self.path = path
        self._file = None
        self._lock = threading.Lock()
        self._closed = False

    def _open(self):
        from datatrove.io import get_datafolder

        folder, _, name = self.path.rpartition("/")
        self._file = get_datafolder(folder or ".").open(name, "wt", compression="gzip")
        return self._file

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if not spans:
            return SpanExportResult.SUCCESS
        line = json.dumps(encode(spans), separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            if self._closed:
                return SpanExportResult.FAILURE
            f = self._file or self._open()
            f.write(line + "\n")
            f.flush()            # each batch on disk (a sync point of the gzip stream): a killed process loses little
        return SpanExportResult.SUCCESS

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        with self._lock:
            if self._file is not None:
                self._file.flush()
        return True

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            f, self._file = self._file, None
        if f is not None:
            f.close()


def as_sampled(s: ReadableSpan) -> ReadableSpan:
    """A copy of an unsampled span marked sampled, so the exporters' processors take it (the page failed)."""
    c = s.context
    ctx = trace_api.SpanContext(c.trace_id, c.span_id, c.is_remote, trace_api.TraceFlags(trace_api.TraceFlags.SAMPLED),
                                c.trace_state)
    return ReadableSpan(name=s.name, context=ctx, parent=s.parent, resource=s.resource, attributes=s.attributes,
                        events=s.events, links=s.links, kind=s.kind, status=s.status, start_time=s.start_time,
                        end_time=s.end_time, instrumentation_scope=s.instrumentation_scope)


class PageBuffer(SpanProcessor):
    """The one span processor of a task's provider, in front of the exporters' processors (``inner``).

    Sampled spans (task spans, the spans of sampled units) go straight on. The spans of an unsampled unit are
    recorded but not sampled (``linecaster.tracing.UnitSampler``): they are held here, per trace, until the unit's
    root span (``linecaster.page``, ``linecaster.item``) ends; if the root's status is an error (the unit failed in
    this stage), the held spans and the root go on, marked sampled; otherwise they are dropped.

    Memory: the ended spans of the units in flight, about 3 KB each (measured), one per block and two per request
    (about 40 KB per page for the twelve blocks of the squiddle recipe). In-process a page or two are in flight; a
    served block holds at most its window and its result queue (``max_window`` + ``4 × max_window`` pages), so with
    the default window of 32 and five served blocks about 800 pages, some 30 MB. A unit that never reaches the end
    of the stage (a block dropped it) is held until the task ends."""

    def __init__(self, inner: list[SpanProcessor]):
        self.inner = list(inner)
        self._held: dict[int, list[ReadableSpan]] = {}
        self._lock = threading.Lock()
        self.exported_failed = 0            # unsampled units exported because they failed

    def on_start(self, span, parent_context=None) -> None:
        pass

    def _forward(self, span: ReadableSpan) -> None:
        for p in self.inner:
            p.on_end(span)

    def on_end(self, span: ReadableSpan) -> None:
        if span.context.trace_flags.sampled:
            self._forward(span)
            return
        tid = span.context.trace_id
        if span.parent is None and span.name in UNIT_ROOTS:
            with self._lock:
                held = self._held.pop(tid, [])
            if span.status.status_code is StatusCode.ERROR:
                self.exported_failed += 1
                for s in (*held, span):
                    self._forward(as_sampled(s))
            return
        with self._lock:
            self._held.setdefault(tid, []).append(span)

    def held(self) -> int:
        """The spans held now (for tests and the memory bound)."""
        with self._lock:
            return sum(len(v) for v in self._held.values())

    def shutdown(self) -> None:
        with self._lock:
            self._held.clear()
        for p in self.inner:
            p.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return all(p.force_flush(timeout_millis) for p in self.inner)
