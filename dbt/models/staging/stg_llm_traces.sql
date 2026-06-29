-- 1:1 cleanup of the LLM telemetry: one row per AI bank-statement-analysis call.
-- This carries the latency + cost + confidence signals the whole project hinges on.
with source as (
    select * from {{ source('raw', 'raw_llm_traces') }}
)

select
    user_id,
    model_version,
    latency_s,
    input_tokens,
    output_tokens,
    cached_tokens,
    cost_usd,
    confidence_score,
    fallback_triggered,
    event_ts
from source
