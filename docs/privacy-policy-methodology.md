# Privacy Policy — Creation Methodology

**ran.accordant.eu** · Written: 2026-06-14 · Applicable law: GDPR + LOPDGDD (Spain)

This document explains how the Rán privacy policy was created, what sources were used, how it was verified against the actual codebase, and what adversarial review process was applied. It is intended for future maintainers who need to update the policy as the service evolves.

---

## Overview

The privacy policy at `ran.accordant.eu/privacy` was not drafted from a template. It was written after a complete audit of the live codebase and verified by an adversarial AI agent acting as a hostile GDPR compliance reviewer. Every claim in the policy is traceable to a specific source.

**Jurisdiction:** Spain (AEPD). The policy follows the GDPR as interpreted by Spanish law (LOPDGDD — Ley Orgánica 3/2018) and AEPD enforcement guidance.

---

## Sources audited

Each file below was read in full before a single line of policy was drafted.

| Source | What was verified |
|---|---|
| `backend/main.py` | Exact fields written to `ops_log.jsonl`; confirmed `BytesIO` (no disk writes); invite code handling; token/cost logging |
| `frontend/index.html` | No `localStorage`, no `sessionStorage`, no CDN scripts, no analytics embeds; `autocomplete="off"` on invite code field; `marked.min.js` served locally |
| `frontend/style.css` | No external font or resource imports |
| `tests/test_zero_retention.py` | 18 tests across 5 categories confirming zero-retention guarantees |
| `scripts/verify-zero-retention.sh` | Audit script confirming no disk writes |
| `/etc/nginx/sites-enabled/ran-web` | Confirmed `access_log off` applies to `/process` and `/health` only — static file requests DO log to the global nginx access log |
| `README.md` (zero-retention section) | End-to-end data flow architecture |
| Anthropic API documentation | 7-day log retention, no training on API inputs/outputs |

---

## Key findings from source audit

These findings directly shaped policy language — each was a decision point.

### 1. nginx access logging is selective, not global
`access_log off` is set **only** for the `/process` and `/health` location blocks. The root `/` location has no such directive, so static file requests (the initial page load) are logged to `/var/log/nginx/access.log` with IP addresses. The policy discloses this distinction explicitly in the data table in section 2.2.

### 2. ops_log invite codes are pseudonymous personal data
The initial draft described `ops_log.jsonl` as containing "no personal data." This was wrong. The `code_used` field stores the invite code for each session. Because codes are issued individually (one per named person), this field is a **pseudonymous identifier** under GDPR Art. 4(1) and Recital 26 (*Breyer v. Germany*). The final policy acknowledges this explicitly and applies legitimate interest (Art. 6.1.f) as the legal basis for operational logging.

### 3. No browser-side storage of any kind
The frontend uses no `localStorage`, `sessionStorage`, cookies, or service workers. The invite code typed into the form lives only in the DOM while the tab is open. `marked.min.js` is served from the same server — no external CDN calls occur.

### 4. Special category data requires explicit consent, not implicit
The PDFs contain disability-related deductions — Art. 9 GDPR special category data. The original framing ("by uploading, you consent") does not satisfy Art. 9.2.a GDPR. EDPB Guidelines 05/2020 §§93–96 require a **separate, deliberate, unambiguous act** specifically directed at the sensitive data. This resulted in the Art. 9 consent checkbox added to the form (see [Frontend change](#frontend-change) below).

### 5. Zero-retention is architectural, not policy-only
The `BytesIO` buffer pattern in `main.py`, confirmed by `test_zero_retention.py` and `verify-zero-retention.sh`, means document content is never on disk at any point. This supports the zero-retention claim in the policy as a technical fact, not an aspiration.

---

## Adversarial review process

After drafting, the policy was submitted to a separate AI agent acting as a **hostile GDPR compliance reviewer** with instructions to find every flaw, gap, and legal risk. The agent had full context about the service architecture and was given 15 specific review tasks:

1. GDPR Art. 13/14 mandatory disclosures
2. LOPDGDD-specific requirements
3. Legal basis defensibility under AEPD standards
4. Anthropic transfer section accuracy (Art. 46 safeguard)
5. Special category data handling (Art. 9)
6. Consent withdrawal mechanism
7. Retention period specificity
8. Automated decision-making (Art. 22) exemption
9. Overclaiming or misleading statements
10. DPO requirement check
11. DPIA requirement check (AEPD AI-specific guidance)
12. Invite code identity linkage
13. Cookie/localStorage disclosure
14. Language creating unintended legal obligations
15. Specific AEPD enforcement risk areas

### Critical findings addressed

| ID | Finding | Fix applied |
|---|---|---|
| C-1 | Art. 9 consent mechanism invalid — uploading ≠ explicit consent | Added blocking Art. 9 checkbox to form (non-pre-ticked, `required`) |
| C-2 | Spanish official version contained English text | Not present in actual file — artifact of compressed context sent to agent |
| C-3 | `ops_log` mischaracterised — invite codes are pseudonymous personal data | Rewrote section 2.3; added pseudonymous identifier language; shifted legal basis to legitimate interest |
| C-4 | Retention "until manual deletion" violates Art. 5.1.e | Set hard 12-month maximum with explicit deletion obligation |
| C-5 | Consent withdrawal violates Art. 7.3 (email harder than uploading) | Clarified that zero-retention makes withdrawal substantively different; made practical meaning explicit |
| C-6 | DPIA not addressed — AEPD AI guidance likely triggers requirement | Added section 5: documented preliminary assessment with risk factors and mitigants; committed to full DPIA before any public/mass-scale expansion |

### Significant findings addressed

| ID | Finding | Fix applied |
|---|---|---|
| S-1 | No Art. 28 DPA confirmation with Anthropic | DPA confirmed in section 4.2; 7-day retention framed as processor function (security/anti-abuse), not independent processing |
| S-2 | "Not used for training **by default**" — dangerous qualifier | Changed to: "This is the contractual policy applicable to API customers, not a default setting" |

---

## Frontend change

The adversarial review identified that the consent mechanism for Art. 9 data was legally invalid. A blocking checkbox was added to `frontend/index.html`:

```html
<div class="consent-field">
  <label>
    <input type="checkbox" id="art9-consent" name="art9_consent" required />
    <span>
      <span class="consent-tag">
        <span class="show-es">Consentimiento expreso — Art. 9 RGPD</span>
        <span class="show-en">Explicit consent — Art. 9 GDPR</span>
      </span>
      <span class="show-es">Entiendo que mi declaración puede contener datos de salud
        o discapacidad. Consiento expresamente su tratamiento por parte de Rán y de
        la API de Anthropic únicamente para generar el informe solicitado.
        <a href="/privacy" target="_blank" rel="noopener">Política de privacidad →</a></span>
      <span class="show-en">I understand my return may contain health or disability
        data. I explicitly consent to its processing by Rán and the Anthropic API
        solely to generate the requested report.
        <a href="/privacy" target="_blank" rel="noopener">Privacy policy →</a></span>
    </span>
  </label>
</div>
```

The link opens the policy in a new tab (`target="_blank"`) so the user does not lose their upload state.

The `required` attribute makes the checkbox a hard gate — the form will not submit without it. The checkbox is bilingual and responds to the language toggle.

CSS styling was added to `frontend/style.css` (`.consent-field` class) to render it in an amber alert box visually consistent with the warning tone required.

---

## Policy structure

The final policy (`frontend/privacy/index.html`) covers 10 sections:

1. **Responsable del tratamiento** — controller identity, DPO waiver rationale
2. **Qué datos tratamos** — all data categories: PDF content, nginx logs, ops_log fields, Art. 9 callout
3. **Finalidades y base jurídica** — purpose/legal basis table including legitimate interest balancing test
4. **Arquitectura de retención cero** — technical zero-retention explanation + Anthropic transfer details (SCCs, DPF, DPA, TIA, ZDR status)
5. **EIPD/DPIA** — preliminary impact assessment with risk factors, mitigants, and scale-up commitment
6. **Conservación y derechos** — retention periods table + all GDPR/LOPDGDD rights including withdrawal
7. **Tratamiento automatizado** — Art. 22 exemption rationale
8. **Cookies** — explicit no-storage declaration
9. **Autoridad de control** — AEPD contact details
10. **Cambios** — update mechanism

The policy is bilingual (ES/EN), Spanish is the official version as required under LOPDGDD Art. 11. Both versions are on the same page with a language toggle consistent with the main application UI.

---

## Maintenance notes

### When to update this policy

Update the policy (and re-run the verification process below) if any of the following change:

- `ops_log.jsonl` fields are added, removed, or renamed
- nginx `access_log` configuration changes for any location block
- A new third-party service receives user data (add as a processor under Art. 28)
- Anthropic's retention policy changes (check [platform.claude.com/docs/en/manage-claude/api-and-data-retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention))
- ZDR with Anthropic is confirmed — update section 4.2 to remove the 7-day caveat
- The service moves from invite-only to public access — triggers full DPIA requirement
- The AI model changes — re-verify processor terms

### Verification checklist for future updates

Before publishing any policy update:

- [ ] Read `backend/main.py` in full — confirm exact `ops_log` fields
- [ ] Read `frontend/index.html` — confirm no new external scripts, storage, or tracking
- [ ] Check nginx config — confirm `access_log` settings for all location blocks
- [ ] Check Anthropic retention policy URL for any changes
- [ ] Run `tests/test_zero_retention.py` — all 18 tests must pass
- [ ] Run `scripts/verify-zero-retention.sh` — must report clean
- [ ] Run adversarial review on the updated draft (see below)

### Running adversarial review

The adversarial review is a separate AI agent pass. Use the following task prompt template:

```
You are an adversarial GDPR/privacy compliance reviewer. Review the following
privacy policy for ran.accordant.eu — a Spanish AI-powered tax return analysis tool.
Be harsh. Find real problems. Do not rubber-stamp it.

Context:
- Jurisdiction: Spain (AEPD, LOPDGDD)
- Architecture: zero-retention (PDFs never touch disk)
- ops_log fields: [list current fields]
- nginx access_log: off for /process and /health; on for static files
- Third-party processor: Anthropic PBC (current retention policy: [X] days)
- Access model: [invite-only | public]

Review against: GDPR Art. 13/14 disclosures, LOPDGDD specifics, legal basis
defensibility, Art. 9 consent mechanism, Art. 46 transfer safeguards,
Art. 5.1.e retention specificity, Art. 7.3 withdrawal equivalence, DPIA
triggers (AEPD AI guidance), DPO requirement, invite-code identity linkage,
browser storage claims, and AEPD enforcement patterns.

[paste updated policy]
```

---

## Files

| File | Description |
|---|---|
| `frontend/privacy/index.html` | Live policy page at `ran.accordant.eu/privacy` |
| `frontend/index.html` | Main application — contains the Art. 9 consent checkbox |
| `frontend/style.css` | Contains `.consent-field` styling |
| `projects/ran/privacy-policy-final.md` | Markdown source (OpenClaw workspace) |
| `docs/privacy-policy-methodology.md` | This file |
