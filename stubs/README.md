# Stub packages

`opencv-contrib-python/`: PaddleX pins `opencv-contrib-python==4.10.0.84` in every extra. That is the
GUI build, which needs `libGL.so.1` and fails to import in slim images (HF Jobs). This stub carries
the same name and version and depends on `opencv-contrib-python-headless==4.10.0.84` (the same cv2
code without GUI), so PaddleX's requirement and its runtime name check are satisfied and `cv2` is the
headless build. `linecaster-paddlex` lists it and points the name at this stub (`[tool.uv.sources]` in
`engines/paddlex/pyproject.toml`), so every environment with PaddleX gets it from `uv lock`; HF Jobs get it as a
direct URL with `#subdirectory=stubs/opencv-contrib-python` (`linecaster.runtime.jobs.dependencies`).
