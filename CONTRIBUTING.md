# Contributing

## Read first

Before making any changes, read **[`AGENTS.md`](AGENTS.md)**. It defines the non-negotiable invariants for this codebase — zero data retention, privacy policy alignment, and the Art. 9 consent requirement. These apply to both humans and AI agents.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/).

```
type(scope): short description

Optional longer body.
```

**Types:**

| Type | When to use |
|---|---|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change with no behaviour change |
| `test` | Adding or updating tests |
| `ci` | CI/CD pipeline changes |
| `chore` | Maintenance (deps, config, tooling) |

**Scopes:** `backend`, `frontend`, `privacy`, `deploy`, `scripts`, `tests`, `docker`, `docs`

**Examples:**
```
feat(backend): add streaming response for Claude API
fix(codes): handle concurrent code consumption race condition
docs(deploy): add Phase 1 VPS migration note
test(backend): add zero-retention verification tests
ci: add GitHub Actions workflow
chore(docker): add .dockerignore
```

## Branch strategy

- `main` — deployable at all times
- Feature branches: `feat/description` or `fix/description`
- Open a PR; CI must pass before merge

## Running tests locally

```bash
pip install -r backend/requirements.txt pytest httpx
pytest tests/ -v
```

## CI pipeline

Every push to `main` runs three jobs via GitHub Actions (`.github/workflows/ci.yml`):

| Job | What it does |
|---|---|
| **Lint + Test** | `ruff check backend/main.py` + `pytest tests/ -v --tb=short` |
| **Docker build check** | `docker build` — catches dependency/Dockerfile issues early |
| **Secrets scan** | `gitleaks detect` scans the diff for accidentally committed secrets |

**CI must be green before a change is considered done.** Check the Actions tab after every push.

### Known CI quirks and fixes

**gitleaks requires standalone install for org repos**  
`gitleaks/gitleaks-action@v2` requires a paid license for GitHub organisations. We install
the binary directly from the release and run it in standalone mode. Do not revert to the
action — it will fail immediately with a license error.

**Test fixtures must redirect `tempfile.tempdir` to `tmp_path`**  
Any test that calls `tempfile.gettempdir()` or `scan_for_pdf_magic(tempfile.gettempdir())`
will hang on CI runners: `/tmp` accumulates thousands of files from tooling and the scan
times out. Both `tmp_env` fixtures monkeypatch `tempfile.tempdir` → `tmp_path` so the scan
covers only the isolated test directory. Do not remove this — the test will silently pass
locally but time out and be killed in CI.

**Module-level constants are cached across tests**  
`main.py` reads `INVITE_CODES_FILE`, `OPS_LOG_FILE`, and `CODE_LOCK_FILE` once at import
time. Tests that import `main` without first deleting `sys.modules["main"]` will use stale
paths from a previous test's environment. Both `tmp_env` fixtures handle this: they delete
the cached module, re-import, and then `monkeypatch.setattr` the constants directly.

**Stuck in-progress runs block the queue**  
GitHub Actions has no automatic timeout on runs for this repo. If you see new pushes stuck
in `queued` state, check for runs stuck in `in_progress` from earlier:
```bash
gh api "/repos/accordant-eu/ran-web/actions/runs?status=in_progress" --jq '.workflow_runs[].id' \
  | xargs -I{} gh api -X POST /repos/accordant-eu/ran-web/actions/runs/{}/cancel
```

### Node.js version notice

`actions/checkout@v4` and `actions/setup-python@v5` run on Node.js 20, which is deprecated
as of June 2026. They will be forced to Node.js 24 after **16 June 2026**. Upgrade to `@v5`
(checkout) and `@v6` (setup-python) when those versions stabilise — or set
`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` in the workflow env.
