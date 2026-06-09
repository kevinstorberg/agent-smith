# Security Automation

Cairn ships GitHub-native security automation by default:

| Concern | Source of truth |
| --- | --- |
| Dependency update PRs | [../.github/dependabot.yml](../.github/dependabot.yml) |
| Lockfile freshness | [../Makefile](../Makefile), [../.github/workflows/security.yml](../.github/workflows/security.yml) |
| Vulnerability scanning | [../Makefile](../Makefile), [../.github/workflows/security.yml](../.github/workflows/security.yml) |
| Secret scanning | [../.github/workflows/security.yml](../.github/workflows/security.yml), [../.pre-commit-config.yaml](../.pre-commit-config.yaml) |

Dependabot is the default updater because it is built into GitHub and covers both
Poetry-managed Python dependencies, npm-managed frontend dependencies, and
GitHub Actions versions. If a downstream application needs Renovate policies,
replace the Dependabot config rather than running both bots against the same
dependency graph.

The security workflow runs on pull requests, pushes to `master`, a weekly
schedule, and manual dispatch. Local developers can run the same Poetry-managed
checks with:

```bash
make audit
make pre-commit
make security
```

`make check` stays fast and deterministic; `make security` is the explicit local
boundary for network-backed vulnerability scanning and full pre-commit execution.
The scanner and hook runner are development dependencies, so CI and local runs
use the same lockfile-managed tool versions.
