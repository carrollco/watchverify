"""Prices as data, from https://dev.meta.ai/docs/pricing-rate-limits read on 2026-10-26. Dollars."""
PRICED_ON = "2026-10-26"
SOURCE = "https://dev.meta.ai/docs/pricing-rate-limits"

_SPARK = {"input": 1.25e-6, "cached": 0.15e-6, "output": 4.25e-6}
_CONTRIB = {"input": 0.10e-6, "cached": 0.002e-6, "output": 0.20e-6}
TOKEN_RATES = {
    "muse-spark-1.3": _SPARK, "muse-spark-1.2": _SPARK, "muse-spark-1.1": _SPARK,
    "muse-spark-1.3-contributor": _CONTRIB, "muse-spark-1.2-contributor": _CONTRIB,
    "muse-wonder-1.0": {"input": 4.00e-6, "cached": 0.20e-6, "output": 20.00e-6},
}
SAM_PER_IMAGE = 2.50 / 1000
SAM_PER_FRAME = 0.20 / 1000
SAM_MIN_FRAMES = 50
IMAGE_PER_IMAGE = 0.01
TRANSCRIBE_PER_HOUR = 0.18


def token_cost(model: str, usage: dict) -> float:
    """usage is the Responses API usage object as a dict. Reasoning tokens are inside output_tokens."""
    r = TOKEN_RATES[model]
    inp = usage.get("input_tokens", 0) or 0
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    return round((inp - cached) * r["input"] + cached * r["cached"] + out * r["output"], 6)


def max_token_cost(model: str, input_tokens: int, max_output_tokens: int) -> float:
    r = TOKEN_RATES[model]
    return round(input_tokens * r["input"] + max_output_tokens * r["output"], 6)


def sam_video_cost(frames: int) -> float:
    return round(max(frames, SAM_MIN_FRAMES) * SAM_PER_FRAME, 6)


def sam_image_cost(images: int = 1) -> float:
    return round(images * SAM_PER_IMAGE, 6)


def transcribe_cost(seconds: float) -> float:
    return round(int(seconds) / 3600 * TRANSCRIBE_PER_HOUR, 6)
