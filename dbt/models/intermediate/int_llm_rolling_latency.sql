-- Rolling-average LLM latency via a WINDOW FUNCTION (the canonical blueprint pattern):
-- a 7-row trailing average per model_version ordered by time. Lets the dashboard show
-- latency *creep* over time, and is the seed for the Phase 4 CUSUM drift monitor.
with traces as (
    select * from {{ ref('stg_llm_traces') }}
)

select
    user_id,
    model_version,
    event_ts,
    latency_s,
    avg(latency_s) over (
        partition by model_version
        order by event_ts
        rows between 6 preceding and current row
    ) as rolling_avg_latency_7,
    count(*) over (
        partition by model_version
        order by event_ts
        rows between 6 preceding and current row
    ) as window_n
from traces
