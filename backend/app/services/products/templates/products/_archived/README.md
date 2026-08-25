# Archived product schemas

Schemas in this directory are **not registered** in `templates/products/__init__.py`,
**not in any DAG**, **not in any sidebar category**, **not in any handler dispatch**.
They are kept in-tree for historical reference and possible future re-activation.

Re-activating a schema:
1. Move it back to `templates/products/<name>.py`.
2. Re-add the `from .<name> import SPEC as _<name>_SPEC` import + the
   `PRODUCT_SCHEMAS["<KEY>"] = _<name>_SPEC` registration in
   `templates/products/__init__.py`.
3. Add the sidebar position + label in `app/app/utils/exporter.py`
   (`_PRODUCT_LABEL_OVERRIDES` and `_CATEGORY_ORDER`).
4. If it participates in chain-resilience refresh, add an entry to
   `app/app/handlers/intel_agent.py:_DOWNSTREAM_PRODUCT_MAP`.
5. If it has a per-target or per-COA constraint, update
   `handlers/product_autodraft.py` (`_PER_TARGET` set, fanout function).

## Current contents

### `target_system_analysis.py` (TSA)

**Why archived (2026-06-08).** TSA is doctrinally an
echelons-above-corps product, authored at theater J-2 / DIA / JIOC
during **Phase 2 of the Joint Targeting Cycle** (JP 3-60 Ch. II ¶3) —
NOT during the corps MDMP / IPOE / D3A cycle. FM 3-60 ¶B-42 verbatim:
*"Developed prior to IPB, TSA templates and matrices … assist IPB
significantly."*

Corps consumes the TSA as a pre-published reference, never authors
it. For IDX 26 / the IBL exercise there is no active theater feeding
TSAs to the corps targeting cell, so the schema sat unused (one
artifact on spark from 2026-05-26, untouched since).

HVTL is the actual intel-cell → targeting-cell bridge product
(ATP 2-01.3 ¶6-58 / FM 3-60 ¶B-42) and does not require TSA as a
dependency — HVTL builds from per-COA SITEMP + threat OOB +
commander's guidance directly.

If a future exercise / real op integrates a theater feed, restore TSA
per the steps above and re-add its `consumes_artifacts` chain into
HVTL.
