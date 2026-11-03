# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["torch==2.14.0"]
# ///
"""Probe an HF Jobs GPU host: driver, CUDA runtime of the torch 2.14 wheel, a matmul on the GPU."""
import platform
import subprocess
import sys
import time

print("python", sys.version.split()[0], platform.machine())
print(subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                     capture_output=True, text=True).stdout.strip())
print(subprocess.run(["nvidia-smi"], capture_output=True, text=True).stdout.splitlines()[2])
import torch  # noqa: E402

print("torch", torch.__version__, "cuda build", torch.version.cuda, "available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device", torch.cuda.get_device_name(0), "capability", torch.cuda.get_device_capability(0))
    a = torch.randn(4096, 4096, device="cuda", dtype=torch.bfloat16)
    torch.cuda.synchronize(); t = time.perf_counter()
    for _ in range(20):
        b = a @ a
    torch.cuda.synchronize()
    print(f"bf16 matmul 4096^2 x20: {time.perf_counter() - t:.3f}s, checksum {float(b.float().abs().mean()):.3f}")
    print("PROBE OK")
else:
    print("PROBE FAIL: CUDA not available")
