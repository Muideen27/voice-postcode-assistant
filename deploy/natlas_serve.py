"""
Serve N-ATLaS on Modal as an OpenAI-compatible API (vLLM on an L4 GPU).

One-time setup:
    modal secret create natlas-api NATLAS_API_KEY=<a long random string you choose>

Debug run (logs stream to your terminal, Ctrl+C stops everything):
    modal serve deploy/natlas_serve.py 2>&1 | tee serve.log

Deploy (gives you a permanent https URL):
    modal deploy deploy/natlas_serve.py

Stop paying when idle: the GPU shuts down automatically after SCALEDOWN seconds without requests.
Uses the same 'hf-cache' volume as natlas_llm_test.py, so the model is not downloaded again.
"""
import os
import subprocess

import modal

MODEL = "NCAIR1/N-ATLaS"
SCALEDOWN = 300  # seconds of no traffic before the GPU shuts down

app = modal.App("natlas-serve")
cache = modal.Volume.from_name("hf-cache", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("build-essential")  # C compiler that vLLM/Triton may need at startup
    .pip_install("vllm==0.30.0", "huggingface_hub")
    .env({
        "HF_HOME": "/cache",
        # FlashInfer's sampler compiles CUDA code at startup and needs nvcc, which this image lacks.
        # Turning it off makes vLLM use its built-in PyTorch sampler instead.
        "VLLM_USE_FLASHINFER_SAMPLER": "0",
    })
)


@app.function(
    image=image,
    gpu="L4",
    volumes={"/cache": cache},
    secrets=[modal.Secret.from_name("huggingface"), modal.Secret.from_name("natlas-api")],
    scaledown_window=SCALEDOWN,
    timeout=60 * 60,
)
@modal.concurrent(max_inputs=16)
@modal.web_server(port=8000, startup_timeout=15 * 60)
def serve():
    cmd = [
        "vllm", "serve", MODEL,
        "--served-model-name", "natlas",
        "--host", "0.0.0.0", "--port", "8000",
        "--max-model-len", "4096",
        "--gpu-memory-utilization", "0.90",
        "--enforce-eager",  # skip CUDA-graph/compile step: simpler, more reliable startup
        "--api-key", os.environ["NATLAS_API_KEY"],
    ]
    subprocess.Popen(cmd)