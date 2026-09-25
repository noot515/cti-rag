# Optional OpenCTI read integration

OpenCTI is an optional cybersecurity source, not part of minimal startup. The integration is read-first and uses only documented `pycti` read methods: paginated STIX core-object/relationship listing plus `get_stix_content(id)`. The inspected client is `pycti 7.260921.0` from OpenCTI master commit `d100109622b67bb28d4e413d051a118d68ea89a4`.

Install `requirements-integrations.txt` only on a source-ingestion worker that needs OpenCTI. Configure:
- `OPENCTI_URL`
- `OPENCTI_TOKEN`: use a dedicated least-privilege read-only token.
- `OPENCTI_TIMEOUT_SECONDS`: 1–30 seconds, default 15.
- `OPENCTI_PAGE_SIZE`: 1–100, default 50.
- `OPENCTI_CA_BUNDLE`: optional CA bundle; TLS verification is enabled by default.
- `OPENCTI_CLIENT_CERT` and optional `OPENCTI_CLIENT_KEY`.
- `OPENCTI_PROXY`: optional explicit HTTP/HTTPS proxy.

The adapter never invokes OpenCTI mutations. Imported bytes enter the existing canonical ingestion/outbox/publication pipeline; a query path cannot write back to OpenCTI.

## Markings

Supported mandatory markings are explicit TLP values:
- TLP:CLEAR / TLP:WHITE -> public
- TLP:GREEN -> internal
- TLP:AMBER / TLP:AMBER+STRICT -> confidential
- TLP:RED -> restricted

Non-public imported evidence is local-only. Unknown/non-TLP mandatory markings are rejected into the normal ingestion quarantine path rather than guessed.

## Synchronization

The connector uses bounded opaque cursors, maximum page size 100, bounded retries/backoff, and explicit service-unavailable errors. A completed full synchronization can reconcile configured previous STIX IDs into tombstones. A resumed partial connector never infers deletions from records it did not observe.

External source failure does not alter the already-published snapshot pointer; publication remains a later, explicit existing lifecycle step.

## Direct-source comparison

An OpenCTI-imported ATT&CK object and the direct ATT&CK STIX object can describe the same upstream STIX object while retaining different source identity, availability metadata, markings, and ingestion provenance. The adapter therefore does not collapse OpenCTI records into direct-source records merely because text or an external ATT&CK ID matches.
