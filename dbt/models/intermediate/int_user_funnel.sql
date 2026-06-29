-- Pivot the long funnel event log into ONE ROW PER USER with a boolean flag per stage.
-- This is the backbone for both the funnel mart and the latency-cohort completion flag.
with events as (
    select * from {{ ref('stg_funnel_events') }}
)

select
    user_id,
    max(case when event_name = 'sign_up'               then 1 else 0 end) as reached_sign_up,
    max(case when event_name = 'bank_link'             then 1 else 0 end) as reached_bank_link,
    max(case when event_name = 'ai_analysis_initiated' then 1 else 0 end) as reached_ai_initiated,
    max(case when event_name = 'ai_analysis_completed' then 1 else 0 end) as reached_ai_completed,
    max(case when event_name = 'loan_terms_offered'    then 1 else 0 end) as reached_offer,
    max(case when event_name = 'loan_accepted'         then 1 else 0 end) as reached_accepted
from events
group by user_id
