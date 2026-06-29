-- THE DIAGNOSTIC MART: AI-analysis completion rate by LLM latency band.
-- This is the evidence that the 32% drop-off is latency-driven (the case for the
-- fallback router). Built from the session-grain intermediate model.
with s as (
    select * from {{ ref('int_session_llm') }}
)

select
    latency_band,
    count(*)                                          as sessions,
    round(avg(latency_s), 2)                          as avg_latency_s,
    sum(completed)                                    as completed_sessions,
    round(100.0 * sum(completed) / count(*), 1)       as completion_rate_pct
from s
group by latency_band
order by latency_band
