# `kyb_cases` legacy shape (Fase 0, Aug 2026)

Snapshot of the 5 documents present in `kyb_cases` at the time Fase 0
started. Everything below is descriptive — **no field is guaranteed to
survive the Fase 1 migration**. This document exists so the migration
can be validated field-by-field against reality, not against wishful
thinking.

Backup copy lives in `kyb_cases_legacy_backup` (5 docs, verbatim copy,
no transformation).

## Sample count

| Bucket | Count | `org_id` | `case_id` |
|---|---|---|---|
| Seed rows | 3 | `null` | `kyb_seed_01`, `kyb_seed_02`, `kyb_seed_03` |
| Real rows | 2 | populated | `kyb_apply__finpact`, `kyb_apply__alemany` |

## Fields observed on seed rows (`org_id: null`)

Observed on `kyb_seed_01` (the richest seed doc):

| Field | Type | Example / notes |
|---|---|---|
| `_id` | ObjectId | Mongo native |
| `case_id` | string | `"kyb_seed_01"` |
| `legal_name` | string | `"Helix Capital S.A."` |
| `commercial_name` | string | `"Helix Capital"` |
| `country` | string (ISO-2) | `"AR"` |
| `type` | string | `"fintech"` |
| `tax_id` | string | `"30-71234567-8"` (NOTE: string in seeds, object in real rows — see below) |
| `incorporation_date` | string (YYYY-MM-DD) | `"2019-03-15"` |
| `documents` | array of object | each `{label, kind, url}`; `url` is a `placehold.co` placeholder |
| `ubos` | array of object | each `{name, ownership_pct, nationality, is_pep, verified}` |
| `checklist` | array of object (len 8) | each `{key, label, checked, checked_by?, checked_at?}` |
| `provider` | string | `"aiprise"` |
| `provider_score` | number | 65 |
| `provider_confidence` | number | 0.65 |
| `provider_flags` | array of string | `["company_active", "no_sanctions_match", "ubo_clean"]` |
| `checks` | object | `{aml: "pass", sanctions: "pass", pep: "pass", travel_rule: "n/a"}` |
| `status` | string | `"approved"` / `"pending"` (see all values below) |
| `applied_at` | string (ISO) | `"2026-05-11T05:20:46.766748+00:00"` |
| `sla_hours_left` | number | `4` (stored — **not computed**) |
| `org_id` | `null` | seed row lacks a real org |
| `timeline` | array of object | each `{ts, by, what, meta}` — append-only in practice |

Statuses seen across the 3 seeds: `"approved"`, `"pending"`, `"pending"`.

The `timeline` array on seed rows contains repeat `decision.approve` entries with
identical `reason` text (`"All 8 checklist items verified per AML/KYB policy."`)
— an artefact of the current bandeja allowing repeat approvals with the same
reason string. Preserve for audit; do not deduplicate.

## Fields observed on real rows

Observed on `kyb_apply__alemany` and `kyb_apply__finpact`. **Not identical
to the seed shape**:

| Field | Type | Notes |
|---|---|---|
| `case_id` | string | `"kyb_apply__alemany"` / `"kyb_apply__finpact"` |
| `org_id` | string | populated (`org_seed_alemany`, `org_seed_finpact`) |
| `legal_name`, `commercial_name`, `country`, `type` | as in seed | |
| `applicant` | object | **new field not in seed** — captures the applicant contact info at apply time |
| `tax_id` | object | **type differs from seed** (string) |
| `documents` | array | `alemany` has 1, `finpact` has 3 — real applies bring their own doc set |
| `ubos` | array | `alemany` has 1 (self-declared) |
| `checklist` | array (len 8) | same shape as seed |
| `checks` | object | same shape as seed |
| `provider` | string | recorded but does NOT imply a real provider ran |
| `provider_score`, `provider_confidence`, `provider_flags` | as in seed | |
| `status` | string | `alemany: "approved"`, `finpact: "in_review"` |
| `applied_at` | string (ISO) | |
| `created_at` | string (ISO) | **new field not in seed** |
| `updated_at` | string (ISO) | **new field not in seed** |
| `is_deleted` | bool | **new field not in seed** (all `false`) |
| `timeline` | array (len 10 on `alemany`) | |
| `decision` | string | `alemany: "approve"` (only present on decided cases) |
| `decision_reason` | string | |
| `decided_by` | string (user_id) | |
| `decided_at` | string (ISO) | |

## Discrepancies to resolve during migration (Fase 1 concerns)

These are called out here so the Fase 1 migration script has a checklist.
**Do not act on them in Fase 0.**

1. `tax_id` is a `string` in seeds but an `object` in real rows — a
   naive migration that assumes one shape will drop data on the other.
2. Seed rows have `org_id: null` — any unique index on `org_id` would
   collide with them (3 nulls). The seeds are demo fixtures and can be
   dropped OR the index must be partial (`{unique:true, partialFilterExpression:{org_id:{$type:"string"}}}`).
   Do not decide unilaterally.
3. `is_deleted`, `created_at`, `updated_at` exist on real rows but not
   on seeds — a `find({is_deleted: {$ne: true}})` will accidentally
   include seeds.
4. `applicant` is only on real rows. Migration will need to construct
   or leave empty for seeds.
5. Documents on seeds are `placehold.co` URLs — clearly not real
   documents. Any tooling that treats them as such is incorrect.
6. `sla_hours_left` is stored as a number on seed rows but the current
   endpoint (`compliance/kyb.py:39`) computes it dynamically. There is
   no reason to keep it stored. Consider dropping during migration.
7. `timeline` contains multiple `decision.approve` entries with
   identical `reason` on the same case — the current bandeja allows
   re-approving. Migration should not reject rows with this pattern.
