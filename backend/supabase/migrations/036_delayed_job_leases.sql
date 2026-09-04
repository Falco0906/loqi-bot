-- Durable delayed-job claims.  Immediate jobs retain a NULL run_at and keep
-- their existing start-immediately behavior.
alter table jobs add column if not exists run_at timestamptz;
alter table jobs add column if not exists lease_owner text;
alter table jobs add column if not exists lease_expires_at timestamptz;

create index if not exists jobs_due_claim_idx
  on jobs(type, run_at, lease_expires_at, created_at)
  where status in ('queued', 'running') and run_at is not null;

-- Claim only due jobs for registered types.  The row lock and conditional
-- update make this a database compare-and-swap: concurrent workers cannot
-- both receive the same job.  A running job becomes eligible again only
-- after its lease expires, which recovers work interrupted by a process stop.
create or replace function claim_due_jobs(
  p_lease_owner text,
  p_job_types text[],
  p_limit integer default 25,
  p_lease_seconds integer default 120
)
returns setof jobs
language plpgsql
as $$
begin
  return query
  with candidates as (
    select id
    from jobs
    where type = any(p_job_types)
      and run_at is not null
      and run_at <= now()
      and status in ('queued', 'running')
      and (lease_expires_at is null or lease_expires_at <= now())
    order by run_at asc, created_at asc
    limit greatest(p_limit, 1)
    for update skip locked
  )
  update jobs as job
  set status = 'running',
      stage = 'Starting...',
      progress = 0,
      lease_owner = p_lease_owner,
      lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 1)),
      updated_at = now()
  from candidates
  where job.id = candidates.id
  returning job.*;
end;
$$;
