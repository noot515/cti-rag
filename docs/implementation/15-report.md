# Phase 15 implementation report — humanities editions, quotations, OCR, and archival provenance

Status: **own deterministic gate passed; cumulative acceptance remains blocked by missing Phase 14, live humanities lifecycle, and inherited external gates**

## Lineage and fingerprints

- Baseline: `15f4050a387bf41b8d77daf05e271ccfe9e522da`
- Previous implemented report: `docs/implementation/13-report.md`
- Phase 14 prerequisite: **not present / blocked**
- Validated Phase 15/16 code checkpoint: `595a48eda8b55ea3870ec6a8ab8391f64160853c`
- Provenance contract / IIIF locator: `d5c30865c28f6e619dbc36dc8c55ae4a79c26ba2`
- Identifier registry: `571f8496a551ca4db2299fc4ef056dec81043edb`
- Humanities DomainSpec: `5251a8a35084da81632b618856cf4bb5cf2c5d5f`
- Fixtures: `45df141f6eedd9169ef5481f33c0ce614775215e`
- Analyzer profiles: `c260d09290db47ca06c6fc5d9cf8241a7f0ae624`
- Source adapters/normalizers: `dfd8dbfcf5f4a86daa5799c04f3eb865a14b1a2b`
- Structured date/passage schema: `a86f7adb533df4ad76d04df315be0213a1363e8b`
- Edition comparison: `049c38b5eb138ad9b583e22df76fe89ed0bea689`
- Phrase retrieval: `74e97339d8d317111f1d8c134e3f29477bd4bcc2`
- Projection layer: `e49b1b2f239ca392075e312a1f64a5d7a7d6d37b`
- Source readiness registry: `549316d51e90c0ebee7d4d1406e9a7f7ec30a0a1`
- Phase 15 test blob: `d33ce4e0edfde7bfaae08a71cffca9573a03c80a`
- Config fingerprint: `a90848b9f9884c344d3fe2cc10cd6ec8c13da591`
- Model fingerprint: **none; Phase 15 deterministic gates invoke no model**

## Implemented

### Work, edition, witness, translation, passage, page, article, and institution identity

The humanities DomainSpec now contains exact namespaces for work, edition, passage, CTS passage, ISBN and DOI-oriented identity. Canonical work/edition/passage identity is not inferred from display title.

Graph/source relations distinguish:
- `edition_of`;
- `witness_of`;
- `translation_of`;
- `article_on_page`;
- `held_by`.

A translation is represented as another edition linked to its source edition. It is not treated as the original-language witness.

### Primary text versus editorial material

Passages carry an explicit role: `primary_text`, `editorial_annotation`, `scholarly_claim`, or `interpretation`.

Only validated primary text enters the primary lexical passage projection. Editorial annotations are retained in a separate annotation projection. Consequently an annotation phrase cannot become a primary quotation merely because it is physically embedded in the same TEI/archive record.

### Original transcription, normalized search text, and OCR alignment

Each source passage preserves:
- original/source transcription;
- normalized retrieval text;
- language;
- transcription quality;
- optional OCR confidence;
- explicit original↔normalized alignment spans.

The newspaper fixture deliberately contains OCR-like errors (`Railr0ad stat1on`) while its search form uses `Railroad station`. Phrase retrieval matches the normalized form but returns the preserved original transcription and its IIIF locator.

A missing phrase returns `EMPTY` with an explicit sampled-corpus reason; absence from the current fixture is not reported as proof of historical nonexistence.

### TEI, IIIF, and citation coordinates

The provenance contract now supports `IiifLocator(canvas_id, page, bbox)` in addition to TEI XPath/canonical passage locators.

The TEI fixture validates source-structure-aware line/passages and separate editorial notes. The newspaper fixture validates IIIF canvas ID, one-based page, bounding box, OCR metadata and archival institution relationships.

CTS identifiers preserve their canonical case rather than being globally lowercased.

### Historical date uncertainty

Exact source dates may use exact validity instants. Month/year/uncertain dates remain structured intervals with explicit precision and label.

The Phase 15 structured fixture verifies that:
- `1813` is represented as `[1813-01-01, 1814-01-01)` with precision `year`;
- `June 1900` is `[1900-06-01, 1900-07-01)` with precision `month`;
- an ancient TEI source with uncertain dating does not receive an invented modern instant.

Interval-overlap predicates query the declared historical bounds directly.

### Edition comparison

`compare_editions` compares two normalized editions deterministically while preserving each edition's own passage ID, locator and original text. Similarity is diagnostic; it does not merge the editions.

### Language/analyzer capability

Analyzer capability is explicit. The validated SQLite profile supports English and limited tokenization profiles for Latin/French while recording the lack of language-specific lemmatization/stemming. Ancient Greek and Arabic are explicitly unsupported in the validated profile rather than silently tokenized under an English assumption.

### Source/rights readiness

Fixture validated:
- short Project Gutenberg public-domain-in-the-USA text fixture;
- synthetic TEI/Perseus-style markup;
- synthetic newspaper/IIIF record modeled on archival metadata semantics.

Deferred:
- BigLAM;
- DPLA;
- Europeana;
- museums;
- other archives.

The manifests preserve rights/source notices and explicitly distinguish fixture validation from a live archive/item-rights lifecycle.

## Validation actually executed

GitHub Actions run `35861752271`, job `107183398771`, Python 3.13.15:

- cumulative deterministic Phase 01–13 + 15–16 suite: **140/140 passed in 11.040 s**
- Phase 15 humanities gate: **7/7 passed in 0.382 s**
- affected legacy API/runtime regressions: **8/8 passed**
- fail-closed registry audit through Phase 16: **passed**, while overall registry status correctly remains `fail`.

Phase 15 verifies:
- two editions of one work remain distinct exact identities;
- normalized OCR retrieval returns the original source transcription;
- TEI XPath and IIIF canvas/page/bbox coordinates remain citable;
- editorial annotation phrases do not enter primary text retrieval;
- translation and original witness remain distinct graph relations;
- year/month/uncertain dates do not become fabricated exact instants;
- historical interval overlap behaves deterministically;
- edition comparison preserves both original texts and locators;
- unsupported language/analyzer combinations remain explicit;
- phrase absence is scoped to the sampled corpus rather than generalized historically.

## Explicit blockers

`phase14-required-prerequisite` is **blocked** because no Phase 14 implementation/report exists on this branch.

`phase15-live-humanities-source-lifecycle` is **blocked**. CI did not perform live Gutenberg/archive catalog reconciliation, item-level rights review, production OCR lifecycle validation, or live multilingual analyzer validation.

Inherited service/model/source gates remain blocked exactly as recorded in `validation/gates.json`.

## Migration and rollback

No live archive, museum, DPLA, Europeana, Perseus or newspaper corpus was downloaded or mutated. The new humanities domain composes through the existing immutable ingestion, snapshot, exact/lexical, graph and structured contracts. Advanced retrieval remains disabled by default. Rollback is commit/snapshot reversal; preserved source revisions and citation coordinates remain immutable.
