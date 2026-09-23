import asyncio,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone

from cti_rag.contracts import AccessLabel,CandidateBudget,IiifLocator,ProcessingClass,SnapshotManifestRef,TemporalMode,TemporalRequest,TeiLocator
from cti_rag.domains.humanities import (
    GUTENBERG_MANIFEST,TEI_MANIFEST,IIIF_MANIFEST,GUTENBERG_COMPARISON_EDITION,
    GutenbergConnector,TeiConnector,IiifConnector,GutenbergNormalizer,TeiNormalizer,IiifNormalizer,
    HumanitiesProjectionRebuilder,HumanitiesPhraseIndex,PhraseSearchRequest,compare_editions,humanities_dataset_registry,
    humanities_source_coverage,HumanitiesSourceStatus,analyzer_profile,overlap_predicates,
)
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.ingestion import IngestionPipeline
from cti_rag.ports import ChannelStatus,EffectiveScope,ProjectionBuildRequest,StructuredRequest
from cti_rag.retrieval import ExactLookupRequest,ExactLookupStatus,PersistentExactIndex
from cti_rag.snapshots import SnapshotCatalogStore,SnapshotPublisher
from cti_rag.structured import DuckDBStructuredPort,Predicate,PredicateOperator,StructuredQuerySpec

UTC=timezone.utc
NOW=datetime(2026,3,1,tzinfo=UTC)
SCOPE=EffectiveScope("alice","public",("humanities",),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_ONLY,),1)

def runtime(td):
    root=Path(td);objects=FileObjectStore(root/"objects");meta=CanonicalMetadataStore.sqlite(root/"meta.db",object_exists=objects.exists);catalog=SnapshotCatalogStore.sqlite(root/"catalog.db")
    return objects,meta,catalog

async def ingest_all(pipeline):
    cursor=None;accepted=0;quarantined=0
    while True:
        result=await pipeline.ingest_page(cursor);accepted+=result["accepted"];quarantined+=result["quarantined"]
        if result["exhausted"]:return accepted,quarantined
        cursor=result["next_cursor"]

def build_bundle(td):
    objects,meta,catalog=runtime(td)
    jobs=(
        (GUTENBERG_MANIFEST,GutenbergConnector(),GutenbergNormalizer()),
        (TEI_MANIFEST,TeiConnector(),TeiNormalizer()),
        (IIIF_MANIFEST,IiifConnector(),IiifNormalizer()),
    )
    for manifest,connector,normalizer in jobs:
        accepted,quarantined=asyncio.run(ingest_all(IngestionPipeline(manifest,connector,normalizer,objects,meta)))
        assert accepted>0 and quarantined==0
    return objects,meta,catalog,HumanitiesProjectionRebuilder(meta,objects).rebuild(system_manifest_id="humanities-manifest")

def one_field(result,name):
    return next(f.value for f in result.items[0].fields if f.name==name)

class Phase15HumanitiesTests(unittest.TestCase):
    def test_source_rights_analyzer_and_deferred_coverage_are_explicit(self):
        self.assertIn("public domain",GUTENBERG_MANIFEST.license_notice.lower())
        self.assertIn("item-level rights",IIIF_MANIFEST.license_notice.lower())
        self.assertTrue(TEI_MANIFEST.license_notice)
        self.assertTrue(analyzer_profile("en").supported)
        self.assertTrue(analyzer_profile("la").supported)
        self.assertFalse(analyzer_profile("grc").supported)
        coverage={x.source_id:x for x in humanities_source_coverage()}
        for sid in ("gutenberg-public-domain-fixture","tei-perseus-style-fixture","chronicling-america-iiif-fixture"):
            self.assertEqual(coverage[sid].status,HumanitiesSourceStatus.FIXTURE_VALIDATED)
        for sid in ("biglam","dpla","europeana","museums","other-archives"):
            self.assertEqual(coverage[sid].status,HumanitiesSourceStatus.DEFERRED)
            self.assertTrue(coverage[sid].reason)
        self.assertFalse(coverage["dpla"].connector);self.assertFalse(coverage["dpla"].normalizer)

    def test_primary_text_annotations_translation_and_witness_stay_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            _objects,_meta,_catalog,bundle=build_bundle(td)
            primary_texts=[d.original_text for d in bundle.lexical]
            annotations=[d.original_text for d in bundle.annotations]
            self.assertTrue(any("truth universally acknowledged" in t for t in primary_texts))
            self.assertTrue(any("Arma virumque cano" in t for t in primary_texts))
            self.assertTrue(any("Railr0ad stat1on" in t for t in primary_texts))
            self.assertFalse(any("editorial secret phrase" in t for t in primary_texts))
            self.assertTrue(any("editorial secret phrase" in t for t in annotations))
            self.assertFalse(any("I sing of arms and the man" in t for t in primary_texts))
            relations={(a.predicate,a.subject.entity_type,a.object.entity_type) for a in bundle.assertions}
            self.assertIn(("translation_of","edition","edition"),relations)
            self.assertIn(("witness_of","witness","edition"),relations)
            self.assertNotIn(("translation_of","witness","edition"),relations)

    def test_ocr_normalized_phrase_returns_original_iiif_quote_and_absence_is_scoped(self):
        with tempfile.TemporaryDirectory() as td:
            _objects,_meta,_catalog,bundle=build_bundle(td);snap=SnapshotManifestRef("humanities-manifest","c",NOW,("lex",))
            phrase=HumanitiesPhraseIndex(bundle.lexical,snap.manifest_id)
            result=asyncio.run(phrase.search(PhraseSearchRequest("Railroad station reopened",SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)))
            self.assertEqual(result.status,ChannelStatus.OK);hit=result.items[0]
            self.assertIn("Railr0ad stat1on",hit.text);self.assertIsInstance(hit.provenance.locator,IiifLocator)
            self.assertEqual(hit.provenance.locator.page,1)
            absent=asyncio.run(phrase.search(PhraseSearchRequest("editorial secret phrase",SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)))
            self.assertEqual(absent.status,ChannelStatus.EMPTY)
            self.assertIn("sampled corpus",absent.reason);self.assertIn("not evidence of historical nonexistence",absent.reason)

    def test_exact_work_editions_and_passages_preserve_separate_coordinates(self):
        with tempfile.TemporaryDirectory() as td:
            _objects,_meta,catalog,bundle=build_bundle(td)
            exact=PersistentExactIndex.sqlite(Path(td)/"exact.db",catalog)
            revisions=tuple(sorted({x.revision_uid for x in bundle.exact}))
            generation=exact.build(ProjectionBuildRequest("humanities-exact","exact",revisions,("canonical/1",),("exact",)),bundle.exact)
            pub=SnapshotPublisher(catalog);pub.stage_generation(generation);manifest=pub.publish(("humanities-exact",),("exact",),created_at=NOW);snap=manifest.to_ref()
            work=exact.lookup(ExactLookupRequest("WORK:AUSTEN-PP",SCOPE,TemporalRequest(TemporalMode.CURRENT),snap,namespace="work-id",object_type="work"))
            left=exact.lookup(ExactLookupRequest("EDITION:PP-GUTENBERG-1342",SCOPE,TemporalRequest(TemporalMode.CURRENT),snap,namespace="edition-id",object_type="edition"))
            right=exact.lookup(ExactLookupRequest("EDITION:PP-COMPARISON-FIXTURE",SCOPE,TemporalRequest(TemporalMode.CURRENT),snap,namespace="edition-id",object_type="edition"))
            passage=exact.lookup(ExactLookupRequest("PASSAGE:PP-OPENING-GUT",SCOPE,TemporalRequest(TemporalMode.CURRENT),snap,namespace="passage-id",object_type="passage"))
            self.assertEqual(work.status,ExactLookupStatus.FOUND);self.assertEqual(left.status,ExactLookupStatus.FOUND);self.assertEqual(right.status,ExactLookupStatus.FOUND);self.assertEqual(passage.status,ExactLookupStatus.FOUND)
            self.assertNotEqual(left.records[0].object_uid,right.records[0].object_uid)
            self.assertNotEqual(left.records[0].revision_uid,right.records[0].revision_uid)
            self.assertIn("truth universally acknowledged",passage.records[0].original_text)

    def test_uncertain_dates_use_intervals_not_fabricated_instants(self):
        with tempfile.TemporaryDirectory() as td:
            _objects,_meta,_catalog,bundle=build_bundle(td)
            rows=[r for ds,r in bundle.structured_rows if ds=="humanities_passages"]
            by_edition={}
            for row in rows:by_edition.setdefault(row["edition_id"],row)
            year=by_edition["EDITION:PP-COMPARISON-FIXTURE"];month=by_edition["EDITION:NEWS-1900-FIXTURE"];tei=by_edition["EDITION:AENEID-LATIN-FIXTURE"]
            self.assertEqual((year["date_start"],year["date_end_exclusive"],year["date_precision"]),("1813-01-01","1814-01-01","year"))
            self.assertIsNone(year["valid_from"]);self.assertIsNone(year["valid_to"])
            self.assertEqual((month["date_start"],month["date_end_exclusive"],month["date_precision"]),("1900-06-01","1900-07-01","month"))
            self.assertIsNone(month["valid_from"]);self.assertIsNone(month["valid_to"])
            self.assertIsNone(tei["date_start"]);self.assertEqual(tei["date_precision"],"uncertain")
            port=DuckDBStructuredPort(humanities_dataset_registry(bundle.structured_rows));snap=SnapshotManifestRef("humanities-manifest","c",NOW,("structured-g",))
            spec=StructuredQuerySpec("humanities_passages",select_fields=("edition_id","date_precision"),predicates=overlap_predicates("1813-06-01","1813-07-01"))
            result=asyncio.run(port.execute(StructuredRequest(spec,SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)))
            self.assertEqual(result.status,ChannelStatus.OK)
            editions=one_field(result,"edition_id")
            editions=(editions,) if isinstance(editions,str) else editions
            self.assertIn("EDITION:PP-COMPARISON-FIXTURE",editions);self.assertNotIn("EDITION:PP-GUTENBERG-1342",editions)

    def test_edition_comparison_keeps_both_original_texts_and_locators(self):
        left=GutenbergNormalizer().normalize(asyncio.run(GutenbergConnector((__import__("cti_rag.domains.humanities",fromlist=["GUTENBERG_EDITION"]).GUTENBERG_EDITION,)).fetch_page(None)).records[0])
        right=GutenbergNormalizer().normalize(asyncio.run(GutenbergConnector((GUTENBERG_COMPARISON_EDITION,)).fetch_page(None)).records[0])
        comp=compare_editions(left.normalized_bytes,right.normalized_bytes)
        self.assertTrue(comp.same_work);self.assertEqual(comp.work_id,"WORK:AUSTEN-PP");self.assertEqual(len(comp.differences),1)
        diff=comp.differences[0];self.assertNotEqual(diff.left_text,diff.right_text);self.assertNotEqual(diff.left_locator,diff.right_locator)
        self.assertGreater(diff.similarity,0.8)

    def test_tei_xpath_and_iiif_coordinates_are_citable_and_annotation_not_exact_primary(self):
        with tempfile.TemporaryDirectory() as td:
            _objects,_meta,_catalog,bundle=build_bundle(td)
            tei=next(d for d in bundle.lexical if "Arma virumque cano" in d.original_text)
            iiif=next(d for d in bundle.lexical if "Railr0ad stat1on" in d.original_text)
            from cti_rag.contracts import locator_from_dict
            self.assertIsInstance(locator_from_dict(json.loads(tei.locator_json)),TeiLocator)
            self.assertIsInstance(locator_from_dict(json.loads(iiif.locator_json)),IiifLocator)
            self.assertFalse(any(x.canonical_id.startswith("ANNOTATION:") for x in bundle.exact))

if __name__=="__main__":unittest.main()
