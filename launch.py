# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "linecaster",
# ]
#
# [tool.uv.sources]
# linecaster = { path = ".", editable = true }
# ///
r"""Launch a recipe or a page preset (a model that reads whole pages) by its name: this finds the pipeline it
runs in and starts that pipeline's script, in the script's own environment.

    uv run launch.py                                   # the recipes and page presets
    uv run launch.py item-texts OUT/pages OUT2         # a recipe: = pipelines/bind.py OUT/pages OUT2 --recipe item-texts
    uv run launch.py chandra-ocr-2 IMAGES OUT          # a page preset: = pipelines/transcribe_vlm.py IMAGES OUT --recognition chandra-ocr-2
    uv run launch.py indra-ocr IMAGES OUT              # a page engine's: = pipelines/transcribe_page.py IMAGES OUT --recognition indra-ocr
    uv run launch.py squiddle IMAGES OUT --backend served --endpoint http://127.0.0.1:8100/v1
                                                       # = pipelines/transcribe_modular.py ... --recipe squiddle, its kraken
                                                       # served from an environment with kraken (its script's serve)
    uv run launch.py squiddle@1 IMAGES OUT --recognition paddlex-ppocrv6-medium   # a slot on top: recorded as an override
    uv run launch.py chandra-ocr-2 IMAGES OUT --on hf-jobs --namespace NS --commit <sha> --tasks 64
    uv run launch.py squiddle --help                   # the pipeline's options

Everything after the name goes to the pipeline (``linecaster.runtime.run``), ``serve`` and ``ray`` too. Your own
combinations: the pipeline scripts in ``pipelines/``.
"""
import os
import sys
from pathlib import Path

from linecaster.catalog import code
from linecaster.catalog.registry import catalog, split_ref

ROOT = Path(__file__).resolve().parent
#: the pipelines page presets run in (a chat VLM's, a page engine's), and their slot
CHAT_PIPELINE, PAGE_PIPELINE, PAGE_SLOT = "transcribe_vlm.v1", "transcribe_page.v1", "recognition"
#: the pipeline whose slots the other presets fill
MODULAR_PIPELINE = "transcribe_modular.v1"


def listing() -> None:
    c = catalog()
    print("recipes")
    for rid, (_, r) in sorted(c.recipes.items()):
        print(f"  {r.ref:<28} {', '.join(f'{k} {v}' for k, v in r.presets.items())}")
    print("page presets (models that read whole pages)")
    for pid, (_, p) in sorted(c.presets.items()):
        if p.page_preset:
            print(f"  {p.ref:<28} {c.model(p.model.id).version or p.model.id} ({c.model(p.model.id).license})")
    print("\nuv run launch.py NAME IMAGES OUT [pipeline options]")


def not_runnable(name: str) -> str:
    """Why ``name`` cannot be launched by itself, and what to run instead."""
    c = catalog()
    if name not in c.presets:
        return f"no recipe or page preset {name!r} (`uv run launch.py` lists them)"
    p = c.preset(name)
    uses = sorted(rid for rid, (_, r) in c.recipes.items() if any(split_ref(x)[0] == name for x in r.presets.values()))
    if p.step == "recognition" and p.capabilities.unit == "region":
        what = (f"reads layout regions: uv run pipelines/transcribe_vlm.py IMAGES OUT --layout <layout preset> "
                f"--recognition {name}")
    else:
        pipeline = code.pipelines(ROOT)[MODULAR_PIPELINE]
        opt = pipeline.slots.get(p.step, p.step)
        what = (f"is one step ({p.step}) of a pipeline: uv run pipelines/{pipeline.source.name} IMAGES OUT --{opt} "
                f"{name} ...")
    return f"{name} {what}" + (f"; recipes with it: {', '.join(uses)}" if uses else "")


def command(name: str, args: list[str]) -> list[str]:
    """The pipeline script's command line for ``name`` (id[@edition] of a recipe or a page preset)."""
    c = catalog()
    rid, _ = split_ref(name)
    if rid in c.recipes:
        pipeline, flag = c.resolve_recipe(name).content["pipeline"], "--recipe"
    elif rid in c.presets and c.preset(rid).page_preset:
        chat = c.preset(rid).engine == "chat.v1"
        pipeline = CHAT_PIPELINE if chat else PAGE_PIPELINE
        flag = f"--{code.pipelines(ROOT)[pipeline].slots[PAGE_SLOT]}"
        if chat and args[:1] == ["serve"]:
            raise SystemExit(f"{name}: a run starts the model's server itself (vLLM or SGLang, from the preset)")
    else:
        raise SystemExit(not_runnable(rid))
    scripts = code.pipelines(ROOT)
    if pipeline not in scripts:
        raise SystemExit(f"{name}: no script for its pipeline {pipeline} (pipelines/*.py: {sorted(scripts)})")
    script = ["uv", "run", "--script", str(scripts[pipeline].source)]
    if args[:1] == ["ray"]:                          # Ray's CLI from the pipeline's environment
        return [*script, *args]
    if args[:1] == ["serve"]:
        return [*script, "serve", flag, name, *args[1:]]
    return [*script, *args, flag, name]


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip(), "\n")
        listing()
        return
    cmd = command(sys.argv[1], sys.argv[2:])
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}     # the pipeline's own environment
    os.execvpe(cmd[0], cmd, env)


if __name__ == "__main__":
    main()
