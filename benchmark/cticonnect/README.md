# CTIConnect external benchmark adapter

This adapter targets **peng-gao-lab/CTIConnect** at commit
`554797d69a51147f1f98fad7198cb2d2b183d0e9` (the 1,859-QA v1.0.0 release).
The current upstream website may describe a later 1,860-item dataset; that is
not silently accepted by this phase.

The external checkout remains outside this repository and retains its own
licenses: code is MIT and benchmark data are CC-BY-4.0. No dataset files are
vendored here.

## Setup

POSIX:

```bash
export CTICONNECT_PATH=/absolute/path/to/CTIConnect
cd "$CTICONNECT_PATH"
git checkout 554797d69a51147f1f98fad7198cb2d2b183d0e9
```

PowerShell:

```powershell
$env:CTICONNECT_PATH = "C:\path\to\CTIConnect"
git -C $env:CTICONNECT_PATH checkout 554797d69a51147f1f98fad7198cb2d2b183d0e9
```

The adapter verifies the Git revision, required licenses, official task counts,
per-task SHA-256 values, structured-corpus hashes/counts, and report count. Any
local modification to benchmark inputs blocks the audit.

## Data boundary

Retrieval receives only `question` plus non-answer task/category/eval-type
metadata. `answer`, `ground_truth`, target identifiers, reference answers,
source clusters, and construction provenance stay in the scoring side of the
adapter. Official CTIConnect identifier scoring is implemented separately and
golden-tested against the pinned upstream behavior.

Structured corpus identity comes from `cve_id`, prefixed `cwe_id`, prefixed
`capec_id`, or `mitre_id`; repeated outer numeric `id` values are provenance
only. The JSON string in `contents` is parsed as nested JSON before indexing.
Reports use only their supplied `preprocessed`, `link`, and `publish_date`
fields; the adapter never fetches report URLs.

`cskg/` is audited as an **extracted** graph artifact. It is not converted into
ground-truth edges, and `cskg/bm25_index.pkl` is never unpickled. The external
experiment rebuilds BM25 from text.

## Evaluation

```bash
python -m benchmark.advanced.run_retrieval_eval \
  --config benchmark/advanced/configs/cticonnect.yaml \
  --output saves/eval/cticonnect
```

Target-object mappings and source-document proxy qrels are reported separately.
Source proxies are explicitly nonexhaustive and are not evidence/path judgments.
Without an explicitly configured answer model, reranker, or judge, those quality
gates remain `not_run`.
