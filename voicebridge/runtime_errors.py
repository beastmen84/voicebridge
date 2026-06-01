CUDA_RUNTIME_ERROR_MARKERS = (
    "cuda was selected",
    "cuda out of memory",
    "cuda error",
    "cudnn",
    "cublas",
    "cannot access an nvidia cuda gpu",
    "no cuda",
    "torch.cuda",
    "nvidia driver",
)


def is_cuda_runtime_failure(message: str) -> bool:
    text = (message or "").lower()
    return any(marker in text for marker in CUDA_RUNTIME_ERROR_MARKERS)
