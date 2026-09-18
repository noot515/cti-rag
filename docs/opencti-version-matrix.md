# OpenCTI / pycti version matrix

Prompt 19 deliberately pins a narrow read-only compatibility surface rather than
using whatever OpenCTI client happens to be installed.

| Component | Prompt 19 status | Version |
| --- | --- | --- |
| OpenCTI platform | supported/pinned | 7.260914.0 |
| pycti | supported/pinned | 7.260914.0 |
| pycti 7.260917.0 | observed newer release, not yet qualified | not supported by this phase |

The supported pair is taken from the OpenCTI 7.260914.0 repository tag, whose
client package also declares pycti 7.260914.0. The phase does not assume that a
newer independently published pycti wheel is compatible without rerunning the
reader and live read-only integration gates.

## Verified read surface

At the pinned tag, AttackPattern, Vulnerability, Report and
StixCoreRelationship expose bounded list calls with first, after, orderBy,
orderMode and withPagination. Pagination includes endCursor and hasNextPage.

Prompt 19 orders finite scans by OpenCTI updated_at and advances only with the
opaque GraphQL endCursor. The captured STIX modified field is preserved
separately as semantic provenance. updated_at is platform-maintenance metadata;
it is not substituted for STIX modified when computing evidence revisions.

A finite scan is therefore a completed traversal over the pages observed during
a capture interval. It is **not** claimed to be an upstream point-in-time
snapshot: concurrent upstream writes can create overlap or changed duplicate
objects, which are recorded as consistency warnings.

## Configuration

The default checked-in OpenCTI profile is sanitized/offline fixture mode and
performs no network access.

Live mode requires an explicit configuration/environment change:

POSIX:

    export ADVANCED_RAG_OPENCTI_MODE=live
    export ADVANCED_RAG_OPENCTI_API_URL=https://opencti.example
    export OPENCTI_API_TOKEN=<read-only-token>

PowerShell:

    $env:ADVANCED_RAG_OPENCTI_MODE = "live"
    $env:ADVANCED_RAG_OPENCTI_API_URL = "https://opencti.example"
    $env:OPENCTI_API_TOKEN = "<read-only-token>"

The token is read only from the environment variable named by opencti.token_env.
It is never serialized into config snapshots or reports.

Install the optional exact client dependency with:

    python -m pip install -r requirements-advanced-opencti.txt

The integration creates no OpenCTI objects, relationships, imports, connectors,
queues or workers. Only client.py can instantiate OpenCTIApiClient.

## Supported entities in Prompt 19

The capture reader requests:
- Attack Pattern
- Vulnerability
- Report
- explicit STIX core relationships

CWE/CAPEC are represented only when they appear in demonstrated explicit fields
or external identifiers of those returned entity shapes. Prompt 19 does not
guess a universal CWE/CAPEC OpenCTI entity method.

Live restricted maintained serving remains disabled until the later policy/
freshness phase specified by the implementation plan.
