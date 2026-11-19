"""From options to components: the reader a command line names (``reader``), the model components' backends and
servers (``engines``, ``preset_models``), the options set over a preset (``overrides``) and the page writer
(``pages``)."""
from __future__ import annotations

import argparse

from linecaster.errors import PipelineConfigError
from linecaster.execution.options import ENGINE_PORT, sample_rule, uri_map


def http(a: argparse.Namespace) -> dict:
    """``linecaster.net.http.HTTPFetcher`` settings from the options: ``--rate-limit`` (each
    worker's; with ``--proxies`` each proxy's), ``--user-agent`` or ``--random-user-agent``, ``--proxies`` and the
    broker through which the workers share them (``--broker``; else ``default_broker``, ``OUT/logs/broker``, with
    proxies or an HTTP policy, whose ``broker`` goes over it)."""
    out = {"iiif_format": getattr(a, "iiif_format", None) or "jpg"}
    if getattr(a, "proxies", None):
        out["proxy_file"] = a.proxies
    if getattr(a, "broker", None):
        out["broker"] = a.broker
    if (getattr(a, "proxies", None) or getattr(a, "http_policy", None)) and getattr(a, "out", None):
        out["default_broker"] = f"{a.out.rstrip('/')}/logs/broker"
        out["broker_run"] = a.out
    if getattr(a, "user_agent", None):
        out["user_agent"] = a.user_agent
    if getattr(a, "random_user_agent", False):
        out["use_fake_user_agent"] = True
    if getattr(a, "rate_limits", None):
        out["rate_limits"] = a.rate_limits
    return out


def reader(a: argparse.Namespace, manifest_folder: str | None = None, task_per_item: bool = False,
           reuse_folder: str | None = None, read_images: bool = True, reuse_index: str | None = None,
           read_metadata: bool | None = None):
    """The reader for the input options. ``manifest_folder``: where ``ManifestReader`` saves the manifests it
    reads (``pipelines/harvest.py``); ``task_per_item``: one item per task when the reader chooses the task count
    (``--parquet`` with ``--item-key``, ``--manifests``; ``pipelines/harvest.py``); ``reuse_folder``: where the
    pipeline writes its images, so a resumed run passes the ones already there on without a request. The sample
    options give the reader its ``sample`` (``sample_rule``); with ``--manifests`` the manifests it reads go to
    ``manifest_folder``, by default ``OUT/manifests``. ``reuse_index``: the index of earlier harvests' page images a
    page-image reader reads copies from (``linecaster.components.readers.earlier``). Without ``read_images`` an image folder's pages carry only
    their images' addresses and page records are read without their images (a component reads them itself).
    ``read_metadata``: a Parquet table's other columns go into the pages' metadata; ``None``: when the images are
    not read."""
    from linecaster.components.readers.images import IMAGE_GLOB, ImageFolderReader, ImageParquetReader
    from linecaster.components.readers.records import PageRecordReader

    sample = sample_rule(a)

    if getattr(a, "items", None):
        from linecaster.components.readers.resources import ResourceReader

        folder, glob = a.items, a.glob_pattern or "**/*.parquet"
        if a.items.endswith(".parquet"):
            parent, _, name = a.items.rpartition("/")
            folder, glob = parent or ".", name
        return ResourceReader(folder, item_key=a.item_key, templates=getattr(a, "templates", None) or None,
                              url_key=a.url_key, kind_key=a.kind_key, name_key=a.name_key, http=http(a),
                              http_policy=a.http_policy, reuse_folder=reuse_folder, max_items=a.max_items, glob_pattern=glob,
                              limit=a.limit, skip=a.skip, reuse_from=getattr(a, "reuse_from", None) or None,
                              follow=getattr(a, "follows", None) or None)
    if getattr(a, "manifests", None):
        from linecaster.components.readers.manifests import ManifestReader

        src, folder, paths_file, glob = a.manifests, a.manifests, a.paths_file, a.glob_pattern
        parent, _, name = src.rpartition("/")
        if src.endswith((".txt", ".txt.gz")):
            folder, paths_file = parent or ".", src
        elif a.manifest_key and src.endswith(".parquet"):
            folder, glob = parent or ".", name
        if sample is not None and manifest_folder is None:      # the manifests the sample reads, for the tasks
            manifest_folder = f"{a.out.rstrip('/')}/manifests"
        return ManifestReader(folder, paths_file=paths_file, glob_pattern=glob, limit=a.limit, skip=a.skip,
                              manifest_key=a.manifest_key, item_key=a.item_key if a.manifest_key else None,
                              manifest_format=a.manifest_format, item_id_pattern=a.item_id_pattern,
                              existing_ocr=a.existing_ocr, manifest_folder=manifest_folder, http=http(a),
                              task_per_item=task_per_item, reuse_folder=reuse_folder,
                              http_policy=getattr(a, "http_policy", None), sample=sample, reuse_index=reuse_index)
    if getattr(a, "pages", None):
        return PageRecordReader(a.pages, http=http(a), http_policy=getattr(a, "http_policy", None),
                                uri_map=uri_map(getattr(a, "uri_map", None) or []), sample=sample,
                                **({} if read_images else {"fetch_images": False}))
    if getattr(a, "page", None):
        folder, _, name = a.page.rstrip("/").rpartition("/")
        return ImageFolderReader(folder or ".", glob_pattern=name, recursive=False)
    if a.parquet:
        folder, glob = a.parquet, a.glob_pattern or "**/*.parquet"
        if a.parquet.endswith(".parquet"):                    # one file: its folder, the file by name
            parent, _, name = a.parquet.rpartition("/")
            folder, glob = parent or ".", name
        return ImageParquetReader(folder, glob_pattern=glob, limit=a.limit,
                                  skip=a.skip, id_key=a.id_key, image_key=a.image_key, item_key=a.item_key,
                                  sequence_key=a.sequence_key, image_folder=a.image_folder, http=http(a),
                                  max_pages=a.max_pages, task_per_item=task_per_item and bool(a.item_key),
                                  reuse_folder=reuse_folder, http_policy=getattr(a, "http_policy", None),
                                  sample=sample, reuse_index=reuse_index, read_images=read_images,
                                  read_metadata=not read_images if read_metadata is None else read_metadata)
    return ImageFolderReader(a.images, paths_file=a.paths_file, glob_pattern=a.glob_pattern or IMAGE_GLOB,
                             item_from_parent=a.item_from_parent, limit=a.limit, skip=a.skip, max_pages=a.max_pages,
                             sequence=a.item_from_parent and not a.paths_file, sample=sample,
                             read_images=read_images)


def engines(a: argparse.Namespace, models: list[dict], script: str, window: int = 32) -> tuple[dict, list]:
    """Backends for the engine ``models`` by name, and the server component that goes last (none in-process or
    with ``--endpoint``). Presets of built-in engines (``layout.single-region.v1``) are in-process either way. With
    ``--endpoint`` the served engines need not be installed here: they run in the server's environment."""
    from linecaster.backends import InProcess, Served
    from linecaster.components.servers.serve import EngineServer
    from linecaster.catalog.registry import in_process_only

    installed = not getattr(a, "describe_only", False)
    # built-in engines (the single-region layout) run in the pipeline's process with either backend
    local = [m for m in models if a.backend == "in-process" or (m.get("preset") and not m.get("spec")
                                                               and in_process_only(m["preset"]))]
    backends = {}
    for m in preset_models(local, installed=installed):
        b = backends[m["name"]] = InProcess(m["spec"], **m.get("kwargs", {}))
        b.preset, b.preset_sha256 = m.get("preset"), m.get("preset_sha256")
        b.overrides = m.get("overrides")
    # with --endpoint the engines run in the server's environment (one with kraken, say), not in this one
    models = preset_models([m for m in models if m not in local], installed=installed and not a.endpoint, served=True)
    if not models:
        return backends, []
    endpoint = a.endpoint or f"http://127.0.0.1:{ENGINE_PORT}/v1"
    backends.update({m["name"]: Served(endpoint, model=m["name"], max_window=window, preset=m.get("preset"),
                                       engine=m.get("spec")) for m in models})
    if a.endpoint:
        return backends, []
    # on HF Jobs the script is not there: the Job's environment has the engines (``dependencies``)
    return backends, [EngineServer(models, port=ENGINE_PORT, script=None if a.on == "hf-jobs" else script)]


def overrides(items: list[str], steps: list[str]) -> dict[str, dict]:
    """``--set STEP.OPTION=VALUE`` items as ``{step: {option: value}}``; values are read as YAML (``4`` is a
    number, ``true`` a boolean, anything else a string)."""
    from linecaster.catalog import yamlio

    out: dict[str, dict] = {}
    for item in items:
        key, sep, value = item.partition("=")
        step, dot, option = key.partition(".")
        if not sep or not dot or not option:
            raise PipelineConfigError(f"--set needs STEP.OPTION=VALUE, got {item!r}")
        if step not in steps:
            raise PipelineConfigError(f"--set {item!r}: no step {step!r} in this pipeline ({', '.join(steps)})")
        out.setdefault(step, {})[option] = yamlio.load(value) if value else ""
    return out


def preset_models(models: list[dict], installed: bool = True, served: bool = False) -> list[dict]:
    """Model dicts with a catalog ``preset`` (``id``) and no ``spec`` get the preset's
    engine and options, and its id (``preset``) and hash (``preset_sha256``); the others stay as they
    are. ``installed=False``: the engines need not be installed here (``describe``). ``served``: for a server,
    which refuses the in-process-only engines."""
    out = []
    for m in models:
        if m.get("preset") and not m.get("spec"):
            from linecaster.catalog.registry import engine_spec

            spec, kwargs, r = engine_spec(m["preset"], installed=installed, served=served)
            m = {**m, "spec": spec, "kwargs": {**kwargs, **m.get("overrides", {})}, "preset": r.ref,
                 "preset_sha256": r.sha256}
        out.append(m)
    return out


def pages(a: argparse.Namespace):
    from linecaster.components.writers.records import PageJsonlWriter

    return PageJsonlWriter(f"{a.out.rstrip('/')}/pages", output_filename="${rank}.jsonl.gz",
                           item_shards=getattr(a, "item_shards", None))
