# Evidence runtime decision log

## D-0001 — Preserve legacy runtime during foundation work
Add a side-effect-free `cti_rag` package beside the historical `packages` package. The latter performs environment/config/model setup on import, which is incompatible with a minimal contract-only dependency boundary.

## D-0002 — Namespaced canonical JSON + SHA-256 identity
Use NFC Unicode normalization, sorted keys, explicit nulls, timezone-aware datetimes, finite numeric values, and structured namespace envelopes. Never concatenate identity fields with ambiguous delimiters.

## D-0003 — Observations are not revision identity
A repeated download of unchanged source content appends an observation to the immutable revision without changing `revision_uid`.

## D-0004 — Merge by citable identity, not text
Identical text from distinct revisions/editions remains separate. Retrieval-attempt IDs and ranking scores are non-citable metadata.

## D-0005 — First lexical target: MySQL 8 FULLTEXT
Prefer a dedicated derived FULLTEXT projection in the already deployed MySQL 8 service before adding another search service. Do not activate it until analyzer, filtering, snapshot, rebuild/rollback, and performance capabilities are validated.
