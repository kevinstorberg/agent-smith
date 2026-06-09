# Job Runtime

Cairn jobs are application background work scheduled through
[src/jobs/](../src/jobs). The app lifespan starts one job runtime and stores it
on `app.state.job_runtime`.

Use jobs for work that can run outside an HTTP request: polling, summaries,
cleanup, refreshes, and durable side effects. Keep business logic in services;
jobs should coordinate services through `JobContext`.

## Source Of Truth

- Runtime config: [config/default.yaml](../config/default.yaml) and
  [config/models.py](../config/models.py)
- Job definitions and registration: [src/jobs/definitions.py](../src/jobs/definitions.py)
  and [src/jobs/registry.py](../src/jobs/registry.py)
- Execution behavior: [src/jobs/runner.py](../src/jobs/runner.py)
- Status and locks: [src/jobs/stores.py](../src/jobs/stores.py) and
  [src/jobs/locks.py](../src/jobs/locks.py)
- Visibility endpoints: [src/jobs/router.py](../src/jobs/router.py)

## Registering Jobs

Register importable job factories with `@register_job`. Persistent scheduling
requires importable module-level factories so APScheduler can restore jobs after
process restart.

```python
from src.jobs import BaseJob, register_job


class RefreshSummariesJob(BaseJob):
    name = "refresh_summaries"

    async def execute(self, context):
        async with context.unit_of_work_factory() as uow:
            ...


@register_job(name="refresh_summaries", trigger_kwargs={"minutes": 15})
def build_refresh_summaries_job():
    return RefreshSummariesJob()
```

Existing direct `JobScheduler.register(job_instance, ...)` remains available
for small local scripts and tests, but app runtime jobs should use definitions.

## Runtime Behavior

`JobRunner` is the only execution path for scheduled and manually triggered
jobs. It applies, in order:

1. enabled/disabled checks
2. lock acquisition
3. retry policy
4. timeout
5. run status recording
6. structured failure logging

Terminal statuses are `success`, `failed`, `timed_out`, `skipped_lock`, and
`disabled`.

## Persistence And Locking

Defaults are local and credential-free:

- scheduler store: memory
- status store: memory
- lock backend: memory

Postgres scheduler/status stores and Redis/Postgres locks are deployment
choices. Use distributed locks for production when more than one app process can
run the same job schedule.

`scripts.doctor` warns when production jobs use a non-distributed lock backend.
Set `jobs.require_distributed_lock=true` to make that a hard failure.

## Visibility

The app includes admin-protected job endpoints:

- `GET /jobs/health`
- `GET /jobs`
- `GET /jobs/{name}/runs`
- `POST /jobs/{name}/run`

They use the standard API error envelope and JWT-backed `admin` permission
checks.
