import asyncio,json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path

from cti_rag.contracts import AccessLabel,ProcessingClass,SnapshotManifestRef,TemporalMode,TemporalRequest,canonical_json_bytes
from cti_rag.domains.quant import (
    SEC_MANIFEST,FRED_MANIFEST,PRICE_MANIFEST,ACTION_MANIFEST,SECURITY_MASTER_MANIFEST,
    SEC_COMPANY_FIXTURE,SEC_FILING_FIXTURE,SEC_FILING_AMENDED_FIXTURE,FRED_ALFRED_FIXTURE,PRICE_CSV_FIXTURE,PRICE_ADJUSTED_CSV_FIXTURE,CORPORATE_ACTION_CSV_FIXTURE,SECURITY_MASTER_FIXTURE,
    SecConnector,FredAlfredConnector,PriceFileConnector,CorporateActionFileConnector,SecurityMasterConnector,
    SecNormalizer,FredAlfredNormalizer,PriceNormalizer,CorporateActionNormalizer,SecurityMasterNormalizer,
    QuantProjectionRebuilder,quant_dataset_registry,TickerAliasResolver,QuantCalculationEngine,EventStudySpec,quant_source_coverage,QuantSourceStatus,
)
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.ingestion import IngestionPipeline
from cti_rag.ports import ChannelStatus,EffectiveScope,ProjectionBuildRequest,SearchKind,SearchRequest,StructuredRequest,SourceRecord
from cti_rag.retrieval import ExactLookupRequest,ExactLookupStatus,PersistentExactIndex,SQLiteFTS5LexicalIndex
from cti_rag.snapshots import SnapshotCatalogStore,SnapshotPublisher
from cti_rag.structured import Aggregation,AggregationFunction,DuckDBStructuredPort,Predicate,PredicateOperator,StructuredQuerySpec

UTC=timezone.utc
NOW=datetime(2026,3,1,tzinfo=UTC)
SCOPE=EffectiveScope("alice","public",("quant",),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_ONLY,),1)

def runtime(td):
    root=Path(td);objects=FileObjectStore(root/"objects");meta=CanonicalMetadataStore.sqlite(root/"meta.db",object_exists=objects.exists);catalog=SnapshotCatalogStore.sqlite(root/"catalog.db")
    return objects,meta,catalog
async def ingest_all(pipeline):
    cursor=None
    while True:
        result=await pipeline.ingest_page(cursor)
        if result["exhausted"]:return result
        cursor=result["next_cursor"]
def field(result,name):return next(f.value for f in result.items[0].fields if f.name==name)

class Phase13QuantTests(unittest.TestCase):
    def _build(self,td):
        objects,meta,catalog=runtime(td)
        jobs=(
            (SEC_MANIFEST,SecConnector(),SecNormalizer()),
            (FRED_MANIFEST,FredAlfredConnector(),FredAlfredNormalizer()),
            (PRICE_MANIFEST,PriceFileConnector(PRICE_CSV_FIXTURE),PriceNormalizer()),
            (PRICE_MANIFEST,PriceFileConnector(PRICE_ADJUSTED_CSV_FIXTURE),PriceNormalizer()),
            (ACTION_MANIFEST,CorporateActionFileConnector(CORPORATE_ACTION_CSV_FIXTURE),CorporateActionNormalizer()),
            (SECURITY_MASTER_MANIFEST,SecurityMasterConnector(),SecurityMasterNormalizer()),
        )
        for manifest,connector,normalizer in jobs:asyncio.run(ingest_all(IngestionPipeline(manifest,connector,normalizer,objects,meta)))
        return objects,meta,catalog,QuantProjectionRebuilder(meta,objects).rebuild(system_manifest_id="quant-manifest")

    def test_source_metadata_real_shape_coordinates_and_readiness_are_explicit(self):
        company=SecNormalizer().normalize(asyncio.run(SecConnector((SEC_COMPANY_FIXTURE,)).fetch_page(None)).records[0]);self.assertEqual(json.loads(company.normalized_bytes)["cik"],"0000123456")
        filing=SecNormalizer().normalize(asyncio.run(SecConnector((SEC_FILING_FIXTURE,)).fetch_page(None)).records[0]);f=json.loads(filing.normalized_bytes)
        self.assertTrue(f["facts"][0]["source_coordinate"].startswith("0000123456-26-000001:ctx-revenue:"));self.assertEqual(f["facts"][0]["period_type"],"duration");self.assertIn("example-8k.htm",f["sections"][0]["source_coordinate"])
        macro=FredAlfredNormalizer().normalize(asyncio.run(FredAlfredConnector().fetch_page(None)).records[0]);self.assertEqual(json.loads(macro.normalized_bytes)["source_coordinate"],"GDPX:2025-12-01:2026-01-10")
        for manifest in (SEC_MANIFEST,FRED_MANIFEST,PRICE_MANIFEST,ACTION_MANIFEST,SECURITY_MASTER_MANIFEST):
            self.assertTrue(manifest.format and manifest.license_notice and manifest.connector_fingerprint and manifest.parser_fingerprint)
        coverage={x.source_id:x for x in quant_source_coverage()}
        for sid in ("sec-edgar-fixture","fred-alfred-fixture","licensed-price-file-fixture","licensed-corporate-action-file-fixture","security-master-fixture","fundamentals","disclosures"):
            self.assertEqual(coverage[sid].status,QuantSourceStatus.FIXTURE_VALIDATED)
        for sid in ("earnings-material","research"):
            self.assertEqual(coverage[sid].status,QuantSourceStatus.DEFERRED);self.assertTrue(coverage[sid].reason)

    def test_exact_company_filing_and_cited_filing_document_retrieval(self):
        with tempfile.TemporaryDirectory() as td:
            objects,meta,catalog,bundle=self._build(td)
            revisions=tuple(sorted({x.revision_uid for x in bundle.exact}))
            exact=PersistentExactIndex.sqlite(Path(td)/"exact.db",catalog);lex=SQLiteFTS5LexicalIndex(Path(td)/"lex.db",catalog)
            eg=exact.build(ProjectionBuildRequest("quant-exact","exact",revisions,("canonical/1",),("exact",)),bundle.exact)
            lg=lex.build(ProjectionBuildRequest("quant-lex","lexical",revisions,("unicode61/1",),("lexical",)),bundle.lexical)
            pub=SnapshotPublisher(catalog);pub.stage_generation(eg);pub.stage_generation(lg);manifest=pub.publish(("quant-exact","quant-lex"),("exact","lexical"),created_at=NOW);snap=manifest.to_ref()
            company=exact.lookup(ExactLookupRequest("0000123456",SCOPE,TemporalRequest(TemporalMode.CURRENT),snap,namespace="cik",object_type="legal-entity"))
            filing=exact.lookup(ExactLookupRequest("0000123456-26-000001",SCOPE,TemporalRequest(TemporalMode.CURRENT),snap,namespace="sec-accession",object_type="sec-filing"))
            self.assertEqual(company.status,ExactLookupStatus.FOUND);self.assertEqual(filing.status,ExactLookupStatus.FOUND)
            from cti_rag.contracts import CandidateBudget
            result=asyncio.run(lex.search(SearchRequest("fictitious cybersecurity incident",SearchKind.LEXICAL,SCOPE,TemporalRequest(TemporalMode.CURRENT),CandidateBudget(10,lexical=10),snap)))
            self.assertEqual(result.status,ChannelStatus.OK);hit=next(x for x in result.items if "cybersecurity incident" in x.text)
            self.assertEqual(hit.provenance.locator.scheme,"sec-filing-section");self.assertIn("0000123456-26-000001:example-8k.htm:item-1-05",hit.provenance.locator.value)

    def test_future_filing_macro_and_corporate_action_revisions_do_not_leak(self):
        with tempfile.TemporaryDirectory() as td:
            _objects,_meta,_catalog,bundle=self._build(td);port=DuckDBStructuredPort(quant_dataset_registry(bundle.structured_rows));snap=SnapshotManifestRef("quant-manifest","c",NOW,("structured-g",))
            fund=StructuredQuerySpec("quant_fundamental",select_fields=("value","accession","amendment","unit"),predicates=(Predicate("cik",PredicateOperator.EQ,"0000123456"),Predicate("tag",PredicateOperator.EQ,"Revenues")))
            early=asyncio.run(port.execute(StructuredRequest(fund,SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-10T00:00:00Z"),snap)))
            current=asyncio.run(port.execute(StructuredRequest(fund,SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)))
            self.assertEqual(field(early,"value"),100.0);self.assertEqual(field(early,"amendment"),False);self.assertEqual(field(current,"value"),105.0);self.assertEqual(field(current,"amendment"),True)
            macro=StructuredQuerySpec("quant_macro",select_fields=("value","realtime_start","unit"),predicates=(Predicate("series_id",PredicateOperator.EQ,"GDPX"),Predicate("observation_date",PredicateOperator.EQ,"2025-12-01")))
            old=asyncio.run(port.execute(StructuredRequest(macro,SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-15T00:00:00Z"),snap)));new=asyncio.run(port.execute(StructuredRequest(macro,SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)))
            self.assertEqual(field(old,"value"),100.0);self.assertEqual(field(new,"value"),110.0)
            action=StructuredQuerySpec("quant_corporate_actions",select_fields=("action_type","effective_date"))
            self.assertEqual(asyncio.run(port.execute(StructuredRequest(action,SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-15T00:00:00Z"),snap))).status,ChannelStatus.EMPTY)

    def test_price_adjustment_is_point_in_time_and_returns_are_reproducible(self):
        with tempfile.TemporaryDirectory() as td:
            _objects,_meta,_catalog,bundle=self._build(td);port=DuckDBStructuredPort(quant_dataset_registry(bundle.structured_rows));snap=SnapshotManifestRef("quant-manifest","c",NOW,("structured-g",))
            prices=StructuredQuerySpec("quant_prices",select_fields=("trading_date","close","adjusted","corporate_action_version"),predicates=(Predicate("security_id",PredicateOperator.EQ,"SEC-EXAMPLE"),),order_by=(("trading_date","asc"),),presentation_limit=20)
            old=asyncio.run(port.execute(StructuredRequest(prices,SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-15T00:00:00Z"),snap)));new=asyncio.run(port.execute(StructuredRequest(prices,SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)))
            self.assertEqual(set(field(old,"adjusted")),{False});self.assertEqual(set(field(new,"adjusted")),{True})
            engine=QuantCalculationEngine(port)
            ret=asyncio.run(engine.returns("SEC-EXAMPLE",SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-15T00:00:00Z"),snap))
            values=next(f.value for f in ret.fields if f.name=="simple_returns");self.assertAlmostEqual(values[-1],0.05,places=12)
            event=asyncio.run(engine.event_study(EventStudySpec("SEC-EXAMPLE","SEC-BENCH","2026-01-09"),SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-15T00:00:00Z"),snap))
            fields={f.name:f.value for f in event.fields};self.assertAlmostEqual(fields["alpha"],0.0,places=12);self.assertAlmostEqual(fields["beta"],2.0,places=12);self.assertAlmostEqual(fields["cumulative_abnormal_return"],0.03,places=12)
            self.assertIn("not a causal or profitability claim",fields["association_label"]);self.assertTrue(event.input_manifest);self.assertTrue(event.revision_uids)

    def test_ticker_aliases_require_exchange_and_time_and_historical_universe_keeps_delisted(self):
        with tempfile.TemporaryDirectory() as td:
            _objects,_meta,_catalog,bundle=self._build(td)
            alias_rows=[row for ds,row in bundle.structured_rows if ds=="quant_security_alias"];resolver=TickerAliasResolver(alias_rows)
            self.assertEqual(resolver.resolve("XYZ","XNAS","2024-06-01T00:00:00Z").security_id,"SEC-OLD")
            self.assertEqual(resolver.resolve("XYZ","XNAS","2026-01-01T00:00:00Z").security_id,"SEC-NEW")
            with self.assertRaises(ValueError):resolver.resolve("XYZ","",None)
            overlap=next(r for r in alias_rows if r["ticker"]=="XYZ" and r["security_id"]=="SEC-OLD");duplicate=alias_rows+[dict(overlap)];ambiguous=TickerAliasResolver(duplicate)
            with self.assertRaisesRegex(ValueError,"ambiguous_or_missing_ticker_alias"):ambiguous.resolve("XYZ","XNAS","2024-06-01T00:00:00Z")
            port=DuckDBStructuredPort(quant_dataset_registry(bundle.structured_rows));snap=SnapshotManifestRef("quant-manifest","c",NOW,("structured-g",))
            spec=StructuredQuerySpec("quant_universe",select_fields=("security_id","delisted_at"),predicates=(Predicate("universe_id",PredicateOperator.EQ,"TEST-100"),),valid_at_iso="2024-06-01T00:00:00Z")
            hist=asyncio.run(port.execute(StructuredRequest(spec,SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)))
            self.assertEqual(field(hist,"security_id"),"SEC-OLD");self.assertEqual(field(hist,"delisted_at"),"2025-07-01T00:00:00Z")

    def test_unknown_units_are_rejected_and_presentation_limit_does_not_change_aggregate(self):
        bad=json.loads(json.dumps(SEC_FILING_FIXTURE));bad["facts"][0]["unit"]="widgets"
        with self.assertRaises(ValueError):SecNormalizer().normalize(SourceRecord("bad",canonical_json_bytes(bad),"bad"))
        with tempfile.TemporaryDirectory() as td:
            _objects,_meta,_catalog,bundle=self._build(td);port=DuckDBStructuredPort(quant_dataset_registry(bundle.structured_rows));snap=SnapshotManifestRef("quant-manifest","c",NOW,("structured-g",))
            spec=StructuredQuerySpec("quant_prices",aggregations=(Aggregation(AggregationFunction.COUNT,None,"row_count"),),presentation_limit=1)
            result=asyncio.run(port.execute(StructuredRequest(spec,SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)))
            self.assertEqual(field(result,"row_count"),10)

if __name__=="__main__":unittest.main()
