# Current state and sequencing handoff

Prompt 02/03 implementation begins from `312e11837bde5b525d277bf7387c57ce30487bb3`, the head of the P00/P01 draft branch.

Reconciliation notes:

1. Prompt 03 was written assuming generic evidence files would be created at that phase, but the predecessor already implemented an initial P01 generic layer. This change strengthens those canonical definitions rather than adding duplicates.
2. `DomainAdapter`, `GraphPattern` and `NormalizedEvidenceBatch` are canonicalized under `packages/evidence/domain.py`; `packages/domains/base.py` remains a compatibility re-export for CTI code.
3. Prompt 02 uses the existing `/chat/stream` baseline unchanged. Its body must contain `user_id`; web retrieval is forced off by the evaluation adapter.
4. Legacy rewrite/rerank behavior is recorded, not described as a controlled ablation.
5. No canonical L0 object mapping is presently verified, so object metrics remain `not_comparable` rather than fabricated.
6. Prompt 04 is next after review. Storage, publication and backend projection phases are not pulled forward.
