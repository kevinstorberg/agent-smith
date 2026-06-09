# Frontend

Cairn includes an optional React + TypeScript frontend under `frontend/`.
Deleting that directory keeps the backend template usable as an API-only app.

Source of truth:

- Frontend commands and dependencies: [../frontend/package.json](../frontend/package.json)
- Frontend env example: [../frontend/.env.example](../frontend/.env.example)
- Frontend runtime config: [../frontend/src/shared/config/](../frontend/src/shared/config/)
- API client and error handling: [../frontend/src/shared/api/](../frontend/src/shared/api/)
- Feature discovery: [../frontend/src/features/registry.ts](../frontend/src/features/registry.ts)
- Generated CRUD feature shell: [../frontend/src/features/resourceCrud.tsx](../frontend/src/features/resourceCrud.tsx)
- Optional FastAPI static mount: [../src/frontend/static.py](../src/frontend/static.py)
- Backend frontend config: [../config/default.yaml](../config/default.yaml), [../config/models.py](../config/models.py)
- Local command entrypoints: [../Makefile](../Makefile), [../docker-compose.yml](../docker-compose.yml)

## Conventions

- Use Vite for local frontend development and static builds.
- Keep backend communication in the shared API client so feature modules do not
  reimplement request IDs, auth headers, or Cairn error envelopes.
- Put generated or app-owned screens under `frontend/src/features/`; the app
  shell discovers feature modules through the registry.
- Use plain CSS tokens in `frontend/src/styles/` as the replaceable visual
  baseline.
- Use the optional backend static mount only when serving built assets from the
  FastAPI process is intentionally enabled.

## Generation

The backend resource generator remains backend-only by default. Add frontend
scaffolding explicitly:

```bash
cairn generate resource project name:string --frontend
```

The generated frontend file is a thin feature registration that delegates CRUD
behavior to the shared resource page.
