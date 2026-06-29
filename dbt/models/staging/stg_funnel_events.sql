-- 1:1 cleanup of the funnel event log (long format: one row per user per stage reached).
with source as (
    select * from {{ source('raw', 'raw_funnel_events') }}
)

select
    user_id,
    event_name,
    event_ts
from source
