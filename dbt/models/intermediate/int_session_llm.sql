-- Session-grain table: one row per AI-analysis call, joined to user attributes and the
-- completion outcome. This is the analysis-ready table for the latency-cohort mart AND
-- for Phase 3's causal work — it deliberately carries the would-be CONFOUNDER columns
-- (requested_amount, device, input_tokens) so the back-door adjustment has them ready
-- once the generator's confounder enrichment lands (see docs/BACKLOG.md).
with traces as (
    select * from {{ ref('stg_llm_traces') }}
),

users as (
    select * from {{ ref('stg_users') }}
),

funnel as (
    select * from {{ ref('int_user_funnel') }}
)

select
    t.user_id,
    t.model_version,
    t.latency_s,
    case
        when t.latency_s < 3 then '1: <3s'
        when t.latency_s < 5 then '2: 3-5s'
        when t.latency_s < 8 then '3: 5-8s'
        else                      '4: >8s'
    end as latency_band,
    t.input_tokens,
    t.output_tokens,
    t.cached_tokens,
    t.cost_usd,
    t.confidence_score,
    t.fallback_triggered,

    -- user attributes carried for the Phase 3 confounder / causal analysis
    u.device,
    u.country,
    u.credit_score,
    u.requested_amount,

    -- outcome: did this AI-analysis session reach 'completed'?
    f.reached_ai_completed as completed,

    t.event_ts
from traces t
left join users  u on t.user_id = u.user_id
left join funnel f on t.user_id = f.user_id
