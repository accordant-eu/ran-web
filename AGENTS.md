# AGENTS.md — Rules for AI Agents and Contributors

This file defines the non-negotiable invariants for this codebase.
**Read this before making any changes.** It applies equally to humans and AI agents.

---

## 1. Zero data retention is a hard invariant

Rán's core promise — and its legal basis — is that no document content ever touches persistent storage.
This is not a policy goal. It is a technical guarantee enforced by architecture.

### What this means in practice

| Action | Allowed? |
|---|---|
| Storing PDF bytes in a `BytesIO` buffer in RAM | ✅ Yes |
| Writing PDF content or extracted text to any file, DB, queue, or log | ❌ Never |
| Writing extracted text to a temp file (even `/tmp`) | ❌ Never |
| Logging any field from the PDF content in `ops_log.jsonl` | ❌ Never |
| Adding a cache layer that persists document content | ❌ Never — requires explicit privacy policy update + DPIA re-assessment first |
| Storing the generated report server-side | ❌ Never |
| Sending document content to any third party other than Anthropic | ❌ Never — requires new Art. 28 DPA, policy update, and user consent |
| Adding analytics/tracking that receives user data | ❌ Never — requires policy update and new consent mechanism |

### Before adding any new third-party service

If you add any integration that receives data from a user session (APIs, analytics, logging services, error trackers, CDNs that log IPs, etc.):

1. Determine if it receives personal data.
2. If yes: obtain an Art. 28 GDPR Data Processing Agreement with that provider.
3. Update the privacy policy (`frontend/privacy/index.html`) to disclose the new processor.
4. Assess whether a new consent mechanism is required.
5. Run an adversarial review on the updated policy (see `docs/privacy-policy-methodology.md`).
6. Do not ship until all of the above are done.

---

## 2. The privacy policy must always reflect the actual code

The privacy policy at `ran.accordant.eu/privacy` makes specific technical claims.
If you change any of the following, the policy **must** be updated in the same commit or PR:

| Code change | Policy section to update |
|---|---|
| Add or rename a field in `ops_log.jsonl` | Section 2.3 (ops log field table) |
| Change `access_log` settings in nginx config | Section 2.2 (nginx logging table) |
| Change the AI model or provider | Section 4.2 (Anthropic transfer section) |
| Add a new data input to the form | Section 2.1 |
| Change retention periods (log rotation, log pruning) | Section 6 (retention table) |
| Add browser-side storage (localStorage, cookies, etc.) | Section 8 (cookies/tracking) |
| Load any external script or resource | Section 8 (cookies/tracking) |
| Change the access model (e.g. invite-only → public) | Sections 3 and 5 (legal basis and DPIA) |

**The policy is a contract with users. Shipping code that invalidates it without updating it is a GDPR violation.**

### Verification before shipping

Before any PR that touches data flows, run:

```bash
pytest tests/ -v                        # all 18 zero-retention tests must pass
bash scripts/verify-zero-retention.sh   # must report clean
```

Then check: does the policy still accurately describe what the code does?
Use the checklist in `docs/privacy-policy-methodology.md`.

---

## 3. ops_log fields are personal data (pseudonymous)

`ops_log.jsonl` contains `code_used`. Because invite codes are issued per person,
this is a pseudonymous identifier under GDPR Art. 4(1) and Recital 26.

- Do not add more identifying fields without updating the legal basis analysis.
- The 12-month retention limit is a legal obligation, not a suggestion.
- Do not extend retention without updating the policy and re-assessing the legitimate interest basis.

---

## 4. The Art. 9 consent checkbox is legally required

The form in `frontend/index.html` includes a non-pre-ticked, blocking checkbox
for explicit consent to process special category data (health/disability) under Art. 9.2.a GDPR.

- Do not remove it.
- Do not pre-tick it.
- Do not make it optional.
- If the form is restructured, ensure the checkbox remains **before** submit and remains `required`.
- The checkbox text must link to `/privacy` so users can read the policy before consenting.

---

## 5. Commit discipline

Use [Conventional Commits](https://www.conventionalcommits.org/). See `CONTRIBUTING.md` for types and scopes.

Any commit that touches data flows, logging, or third-party integrations should include
a note in the commit body confirming the privacy policy was checked and is still accurate,
or referencing the policy update included in the same commit.

Example:
```
feat(backend): add request_id field to ops_log

Adds a random UUID per request for easier debugging across log lines.
Does not contain personal data. Privacy policy section 2.3 field table updated.
```

---

## 6. Expanding the service

The current DPIA assessment (see `docs/privacy-policy-methodology.md`) is valid for
invite-only, small-scale operation. If you plan to:

- Open access to the public (remove invite codes)
- Process more than ~1,000 returns/month
- Add new categories of sensitive data
- Add automated decision-making with legal or significant effects

...a **full DPIA must be completed before launch**, and the AEPD may need to be consulted.
Do not proceed without reviewing this with someone who understands GDPR compliance.

---

*These rules exist because Rán processes Spanish tax returns — among the most sensitive
documents a person holds. The architecture earns user trust. Don't break it.*
