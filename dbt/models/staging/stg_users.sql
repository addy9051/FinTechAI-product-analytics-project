-- 1:1 cleanup of raw_users: one row per signup. No business logic here on purpose.
with source as (
    select * from {{ source('raw', 'raw_users') }}
)

select
    user_id,
    signup_ts,
    country,
    device,
    credit_score,
    requested_amount
from source
