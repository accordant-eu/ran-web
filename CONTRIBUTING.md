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
