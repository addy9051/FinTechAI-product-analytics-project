-- 1:1 cleanup of accepted loans, including the matured default outcome (the guardrail).
with source as (
    select * from {{ source('raw', 'raw_loans') }}
)

select
    user_id,
    amount,
    credit_score,
    default_prob,
    defaulted,
    accepted_ts
from source
