# Current state and sequencing handoff

Prompt 04 begins from `d210c0fde63df3ed765e0310f699f913722947d4`, the validated Prompt 02/03 head. Prompt 04 is stacked on `feat/advanced-04-cti-domain-adapter`.

Reconciliation notes:

1. Prompt 03 canonicalized the domain-neutral contracts under `packages/evidence`; Prompt 04 therefore reuses the existing CTI package instead of creating a second compatibility package.
2. Prompt 04 adds only the demonstrated generic requirement that `NormalizedEvidenceBatch` can carry typed chunks. CTI-specific quarantine, marking, identifier, alias and serialization behavior remains owned by `packages/domains/cti`.
3. The predecessor legacy synthetic fixture is retained for L0 comparison. Prompt 04 makes its public status explicit with `unmarked_data_public=true`; because Prompt 02 pins raw bytes, `benchmark/advanced/manifests/legacy-corpus.json` is updated to the new fixture SHA-256.
4. Prompt 04 corpus/query/qrel/path fixtures are physically separated. No qrel, answer or path label is added to retrieval inputs.
5. Aliases are ambiguous lookup candidates, never exact identifiers. Report object references remain explicit non-causal assertions. Unsupported or unresolved markings and unsupported granular selectors fail closed through quarantine/suppression.
6. Prompt 05 is the next phase. Durable raw storage/catalog behavior, snapshot activation, backend projection, retrieval orchestration and service integration are not part of Prompt 04.

Validation state: the focused Prompt 04 sandbox gate passed (`28 passed`) plus compile/diff checks. Exact Prompt 04 Python 3.11 and full-repository collection are still `not_run`; the earlier P00-P03 Windows result does not automatically certify new Prompt 04 code.
