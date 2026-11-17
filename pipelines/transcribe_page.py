# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     # Ray for --on ray and the ray command (a Job leaves it out); nvImageCodec to decode page images on NVIDIA
#     # GPUs, used where the machine has one (its wheels install anywhere)
#     "linecaster[ray,nvimgcodec]",
#     # the page engines: Indra (ONNX Runtime), the vendors' HTTP APIs (Falcon-OCR, OXR), Surya (on vLLM)
#     "linecaster-indra",
#     "linecaster-services",
#     "linecaster-surya",
# ]
#
# [tool.uv]
# # surya-ocr 0.23.0 declares pillow<11, and linecaster needs Pillow>=11: the override wins (NOTES.md: Four more page
# # readers). torch is surya-ocr's (>=2.7,<3), not pinned: no kraken here
# override-dependencies = [
#     "pillow==12.3.0",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# linecaster-indra = { path = "../engines/indra", editable = true }
# linecaster-services = { path = "../engines/services", editable = true }
# linecaster-surya = { path = "../engines/surya", editable = true }
# ///
"""The page-engine pipeline (``transcribe_page.v1``): its components, options and slots are the pipeline template
``linecaster.templates.transcribe_page``; this script gives it its environment. ``--help`` lists the options."""
from linecaster.templates import transcribe_page as template
from linecaster.execution import run

if __name__ == "__main__":
    run.main(__file__, template.__doc__, template.options, template.models, template.pipeline, template.PIPELINE, template.SLOTS)
