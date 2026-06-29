-- The end-to-end funnel: unique users per stage + step-over-step conversion.
-- pct_of_top = retention vs sign_up; step_conversion_pct = vs the previous stage
-- (the AI-analysis step is where ~33% is lost).
with f as (
    select * from {{ ref('int_user_funnel') }}
),

stages as (
    select 1 as stage_order, 'sign_up'               as stage, sum(reached_sign_up)    as users from f
    union all
    select 2,                'bank_link',                       sum(reached_bank_link)        from f
    union all
    select 3,                'ai_analysis_initiated',           sum(reached_ai_initiated)     from f
    union all
    select 4,                'ai_analysis_completed',           sum(reached_ai_completed)     from f
    union all
    select 5,                'loan_terms_offered',              sum(reached_offer)            from f
    union all
    select 6,                'loan_accepted',                   sum(reached_accepted)         from f
)

select
    stage_order,
    stage,
    users,
    round(100.0 * users / max(users) over (), 1)                          as pct_of_top,
    round(100.0 * users / lag(users) over (order by stage_order), 1)      as step_conversion_pct
from stages
order by stage_order
