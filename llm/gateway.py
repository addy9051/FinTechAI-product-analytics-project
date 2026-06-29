"""
LLM gateway with a latency-fallback router + Langfuse tracing (Phase 2, the headline).

The production blueprint routes a primary model -> a faster/cheaper fallback model
when latency exceeds a threshold. We reproduce that locally and at $0 cost:

  primary = ollama_chat/llama3.2     (3B, slower, slightly sharper)
  fast    = ollama_chat/llama3.2:1b  (1B, much faster) -- the fallback target

Mechanism: we call the primary with a hard `timeout` equal to the fallback
threshold (4s). If the primary doesn't answer in time (latency > 4s) — or errors —
we fall back to the fast model.

Tracing (Langfuse): instrumented per the official Langfuse skill's instrumentation
best practices, using LiteLLM's `langfuse_otel` callback — the OpenTelemetry path
that matches the Langfuse v3/v4 SDK (NOT the legacy "langfuse" callback, which needs
the old v2 SDK). The integration auto-captures model + token usage + cost; we add:
  - descriptive generation names ("primary-attempt" / "fallback")
  - one trace_id per analysis, shared by both attempts -> the timed-out primary AND
    the fallback appear together in a single trace (you can see the router decision)
  - user_id for cost attribution, and feature tags
Tracing is OPTIONAL: with no LANGFUSE keys set, the gateway runs unchanged, untraced.

Setup: copy .env.example -> .env, add your Langfuse keys. Docs:
https://langfuse.com/integrations/frameworks/litellm-sdk

Run a one-shot demo:  uv run python llm/gateway.py
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env BEFORE litellm's Langfuse callback initializes (documented Langfuse
# pitfall: initializing before environment variables are loaded).
load_dotenv()

import litellm  # noqa: E402

litellm.suppress_debug_info = True
litellm.drop_params = True

OLLAMA_BASE = "http://localhost:11434"
PRIMARY_MODEL = "ollama_chat/llama3.2"
FAST_MODEL = "ollama_chat/llama3.2:1b"
FALLBACK_THRESHOLD_S = 4.0  # CLAUDE.md: fallback fires when latency exceeds 4s

# Notional cloud-equivalent pricing ($ per 1k tokens). Ollama is free locally; this
# mirrors the generator's MODELS rates so the gateway can report a cost per call.
PRICING = {
    "primary": {"in": 0.0030, "out": 0.0150},
    "fast":    {"in": 0.0008, "out": 0.0040},
}


def _setup_langfuse() -> bool:
    """Enable Langfuse tracing via LiteLLM's OTEL callback iff valid keys are present.
    Returns whether tracing is active. Uses `langfuse_otel` (the v3/v4 OTEL path) per
    https://langfuse.com/integrations/frameworks/litellm-sdk."""
    pub = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sec = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not (pub.startswith("pk-lf-") and sec.startswith("sk-lf-")):
        return False
    # litellm's OTEL callback reads LANGFUSE_OTEL_HOST. Derive it from the canonical
    # LANGFUSE_BASE_URL (what the langfuse v4 SDK + langfuse-cli use), falling back to
    # the legacy LANGFUSE_HOST, then the EU default — so one region var in .env suffices.
    if not os.environ.get("LANGFUSE_OTEL_HOST"):
        os.environ["LANGFUSE_OTEL_HOST"] = (
            os.environ.get("LANGFUSE_BASE_URL")
            or os.environ.get("LANGFUSE_HOST")
            or "https://cloud.langfuse.com"
        )
    litellm.callbacks = ["langfuse_otel"]
    return True


LANGFUSE_ENABLED = _setup_langfuse()


@dataclass
class AnalysisResult:
    tier: str                 # 'primary' or 'fast'
    model: str
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    fallback_triggered: bool
    fallback_reason: str | None
    notional_cost_usd: float
    text: str
    session_id: str | None    # Langfuse session grouping the attempt(s); set when tracing on


def _cost(tier: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = PRICING[tier]
    return round(prompt_tokens / 1000 * p["in"] + completion_tokens / 1000 * p["out"], 6)


def _call(model: str, messages: list[dict], timeout: float, max_tokens: int,
          metadata: dict | None = None):
    """One LiteLLM call to Ollama, timed. `metadata` flows to the Langfuse callback."""
    t0 = time.perf_counter()
    resp = litellm.completion(
        model=model,
        messages=messages,
        api_base=OLLAMA_BASE,
        timeout=timeout,
        max_tokens=max_tokens,
        metadata=metadata or {},
    )
    latency = time.perf_counter() - t0
    return resp, latency


def warmup(models: tuple[str, ...] = (PRIMARY_MODEL, FAST_MODEL), timeout: float = 300):
    """Pre-load each model into memory with a 1-token request. Local Ollama serves one
    model at a time, so paying the (one-time, multi-second) cold-load cost up front keeps
    it from being conflated with — and blocking — the latency-fallback routing. In
    production the models are already resident, so this mirrors steady state."""
    loaded = []
    for m in models:
        t0 = time.perf_counter()
        litellm.completion(model=m, messages=[{"role": "user", "content": "ping"}],
                           api_base=OLLAMA_BASE, max_tokens=1, timeout=timeout,
                           metadata={"generation_name": "warmup", "tags": ["warmup"]})
        loaded.append((m, time.perf_counter() - t0))
    return loaded


def flush() -> None:
    """Flush buffered OTEL spans so traces are sent before a short script exits
    (documented Langfuse pitfall: 'No flush() in scripts -> traces never sent')."""
    if not LANGFUSE_ENABLED:
        return
    try:
        from opentelemetry import trace as _otel
        provider = _otel.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception:
        pass


def analyze(
    messages: list[dict],
    *,
    user_id: str = "anonymous",
    threshold_s: float = FALLBACK_THRESHOLD_S,
    max_tokens: int = 220,
) -> AnalysisResult:
    """Run the primary model under a latency budget; fall back to the fast model if it
    blows the budget (or errors). Both attempts share one trace_id so the timed-out
    primary and the fallback are visible together in a single Langfuse trace."""
    # One session_id per analysis groups the primary attempt + the fallback together in
    # Langfuse's Sessions view. (With the OTEL integration each LLM call gets its own
    # trace, so session_id — not a shared trace_id — is the correct grouping key.)
    session_id = uuid.uuid4().hex
    base_meta = {
        "session_id": session_id,
        "trace_name": "bank-statement-analysis",
        "trace_user_id": user_id,
        "tags": ["loan-underwriting", "phase-2", "fallback-router"],
    }

    fallback = False
    reason: str | None = None
    try:
        # Hard timeout == the fallback threshold: exceeding 4s *is* the trigger.
        meta = {**base_meta, "generation_name": "primary-attempt"}
        resp, latency = _call(PRIMARY_MODEL, messages, threshold_s, max_tokens, meta)
        tier, model = "primary", PRIMARY_MODEL
    except Exception as e:  # noqa: BLE001 - any primary failure routes to the fallback
        fallback = True
        # litellm wraps an Ollama timeout inside APIConnectionError, so check the message
        # too — exceeding the 4s budget is the real trigger we want to surface.
        is_timeout = "timeout" in type(e).__name__.lower() or "timeout" in str(e).lower()
        reason = "latency>4s (timeout)" if is_timeout else type(e).__name__
        meta = {**base_meta, "generation_name": "fallback",
                "tags": base_meta["tags"] + ["fallback-fired"]}
        # Fast model gets a generous timeout — it's the safety net, we don't want it to fail too.
        resp, latency = _call(FAST_MODEL, messages, 90, max_tokens, meta)
        tier, model = "fast", FAST_MODEL

    usage = resp.get("usage") or {}
    pin = int(usage.get("prompt_tokens") or 0)
    pout = int(usage.get("completion_tokens") or 0)
    text = resp["choices"][0]["message"]["content"]

    return AnalysisResult(
        tier=tier,
        model=model,
        latency_s=round(latency, 3),
        prompt_tokens=pin,
        completion_tokens=pout,
        fallback_triggered=fallback,
        fallback_reason=reason,
        notional_cost_usd=_cost(tier, pin, pout),
        text=text,
        session_id=session_id if LANGFUSE_ENABLED else None,
    )


# --- A representative bank-statement underwriting prompt (synthetic) ----------
_DEMO_MESSAGES = [
    {
        "role": "system",
        "content": (
            "You are a loan underwriting assistant. Given a short bank-statement "
            "summary, give a 3-sentence risk assessment and a clear recommendation "
            "(approve / review / decline). Be concise."
        ),
    },
    {
        "role": "user",
        "content": (
            "Applicant: 90-day summary. Avg monthly income $4,200 (regular payroll). "
            "Avg monthly outflow $3,950. Two NSF/overdraft events in the last 90 days. "
            "Existing loan repayments $600/mo. Requested amount $3,000. "
            "Account age 4 years; balance trend slightly declining."
        ),
    },
]


def _demo() -> None:
    print("=== LLM fallback router demo ===")
    print(f"primary: {PRIMARY_MODEL}  | fast: {FAST_MODEL}  | threshold: {FALLBACK_THRESHOLD_S}s")
    print(f"Langfuse tracing: {'ENABLED' if LANGFUSE_ENABLED else 'disabled (no keys in .env)'}\n")
    print("warming up models (one-time cold load)...")
    for m, dt in warmup():
        print(f"  loaded {m:24s} in {dt:5.1f}s")
    print()
    r = analyze(_DEMO_MESSAGES, user_id="applicant-demo-001", max_tokens=140)
    flush()  # send buffered traces before the script exits
    print(f"served by    : {r.model}  ({r.tier})")
    print(f"fallback     : {r.fallback_triggered}" + (f"  [{r.fallback_reason}]" if r.fallback_triggered else ""))
    print(f"latency      : {r.latency_s}s")
    print(f"tokens       : {r.prompt_tokens} in / {r.completion_tokens} out")
    print(f"notional cost: ${r.notional_cost_usd}")
    if r.session_id:
        print(f"langfuse session: {r.session_id}  (Sessions tab; traces tagged 'fallback-router')")
    print("\n--- response ---")
    print(r.text)


if __name__ == "__main__":
    _demo()
