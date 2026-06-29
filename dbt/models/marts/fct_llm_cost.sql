-- LLM COST PER CONVERTED USER — the unit-economics headline of Phase 2.
-- "Converted" = the user reached loan_accepted. We pay for EVERY AI analysis (converters
-- and non-converters alike), so:
--     cost_per_converted_user = total LLM spend / funded loans
-- is the true cost of acquiring a funded loan via the AI step (the number a CFO watches).
-- Grain: one row per model_version + a ROLLUP grand-total row (model_version = 'ALL').
with traces as (
    select * from {{ ref('stg_llm_traces') }}
),

funnel as (
    select * from {{ ref('int_user_funnel') }}
),

joined as (
    select
        t.user_id,
        t.model_version,
        t.cost_usd,
        coalesce(f.reached_accepted, 0) as converted
    from traces t
    left join funnel f on t.user_id = f.user_id
)

select
    coalesce(model_version, 'ALL')                       as model_version,
    count(*)                                             as sessions,
    sum(converted)                                       as converted_users,
    round(sum(cost_usd), 4)                              as total_cost_usd,
    round(avg(cost_usd), 6)                              as avg_cost_per_session,
    round(sum(cost_usd) / nullif(sum(converted), 0), 6) as cost_per_converted_user
from joined
group by rollup (model_version)
order by grouping(model_version), model_version
