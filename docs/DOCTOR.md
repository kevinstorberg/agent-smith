# Doctor Command

Run the doctor after cloning, changing `.env.*`, switching backends, or before
shipping a new application from the template:

```bash
make doctor
```

The command checks Poetry, env files, settings, production security readiness,
job runtime readiness, installed dependencies, selected optional backends, selected provider
credentials, database connectivity, and Alembic migration state.

Useful variants:

```bash
poetry run python -m scripts.doctor --skip-db
poetry run python -m scripts.doctor --all-optional
poetry run python -m scripts.doctor --strict
poetry run python -m scripts.doctor --require-provider-credentials
```

Provider credentials are warnings by default so a local app can bootstrap without
paid API keys. `--strict` or `--require-provider-credentials` turns missing
selected LLM credentials into failures.

`--all-optional` checks every optional backend dependency group declared in
[pyproject.toml](../pyproject.toml), including provider utilities that are not
selected by the default YAML config.
