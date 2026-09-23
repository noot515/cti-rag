import asyncio,unittest
from types import SimpleNamespace
from cti_rag.context import ContextBudget,ContextPacker,RerankOutcome
from cti_rag.planning import FusionResult
from cti_rag.contracts import AccessLabel,ProcessingClass,SnapshotManifestRef,TemporalMode,TemporalRequest
from cti_rag.ports import ChannelStatus,EffectiveScope,StructuredRequest
from cti_rag.structured import (
    Aggregation,AggregationFunction,DuckDBStructuredPort,Predicate,PredicateOperator,StructuredCompiler,StructuredQuerySpec,
    StructuredValidationError,UnknownAvailabilityPolicy,fixture_registry,
)

def scope(domain):
    return EffectiveScope("alice","public",(domain,),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_ONLY,),1)
def snap(manifest="manifest-late"):
    from datetime import datetime,timezone
    return SnapshotManifestRef(manifest,"corpus",datetime(2026,1,1,tzinfo=timezone.utc),("structured-g",))
def run(port,spec,domain,temporal=None,manifest="manifest-late"):
    temporal=temporal or TemporalRequest(TemporalMode.CURRENT)
    return asyncio.run(port.execute(StructuredRequest(spec,scope(domain),temporal,snap(manifest))))

class Phase9StructuredTemporalTests(unittest.TestCase):
    def setUp(self):self.registry=fixture_registry();self.port=DuckDBStructuredPort(self.registry)

    def test_full_corpus_count_precedes_presentation_limit(self):
        spec=StructuredQuerySpec("vulnerability",aggregations=(Aggregation(AggregationFunction.COUNT,None,"count"),),presentation_limit=1)
        result=run(self.port,spec,"cybersecurity")
        self.assertEqual(result.status,ChannelStatus.OK);self.assertEqual(result.items[0].fields[0].value,120);self.assertEqual(result.items[0].fields[0].unit,"count")

    def test_numeric_vulnerability_filter_is_typed_and_reproducible(self):
        spec=StructuredQuerySpec("vulnerability",predicates=(Predicate("cvss",PredicateOperator.GE,7.0),),aggregations=(Aggregation(AggregationFunction.COUNT,None,"high_cvss"),))
        result=run(self.port,spec,"cybersecurity");item=result.items[0]
        self.assertEqual(item.fields[0].value,44);self.assertEqual(item.dataset_snapshot,"vuln-fixture/1");self.assertTrue(item.query_spec_hash);self.assertTrue(item.input_manifest);self.assertEqual(item.calculation_version,"duckdb-structured/1")

    def test_revised_future_macro_observation_never_enters_earlier_public_knowledge(self):
        spec=StructuredQuerySpec("macro",select_fields=("series_id","value"),predicates=(Predicate("series_id",PredicateOperator.EQ,"GDPX"),))
        early=run(self.port,spec,"quant",TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2025-01-10T00:00:00Z"))
        later=run(self.port,spec,"quant",TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-03-01T00:00:00Z"))
        self.assertEqual(early.items[0].fields[1].value,100.0);self.assertEqual(later.items[0].fields[1].value,110.0)
        self.assertEqual(early.items[0].revision_uids,("macro-r1",));self.assertEqual(later.items[0].revision_uids,("macro-r2",))

    def test_public_knowledge_and_system_replay_differ_for_late_ingestion(self):
        spec=StructuredQuerySpec("macro",select_fields=("series_id","value"),predicates=(Predicate("series_id",PredicateOperator.EQ,"LATE"),))
        public=run(self.port,spec,"quant",TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2025-01-20T00:00:00Z"))
        replay=run(self.port,spec,"quant",TemporalRequest(TemporalMode.HISTORICAL_SYSTEM_REPLAY,snapshot_manifest_id="manifest-early"),manifest="manifest-early")
        self.assertEqual(public.status,ChannelStatus.OK);self.assertEqual(public.items[0].fields[1].value,5.0);self.assertEqual(replay.status,ChannelStatus.EMPTY)

    def test_unknown_availability_is_conservatively_excluded_or_explicitly_rejected(self):
        base=dict(dataset_id="macro",select_fields=("series_id","value"),predicates=(Predicate("series_id",PredicateOperator.EQ,"UNKNOWN"),))
        temporal=TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2025-12-31T00:00:00Z")
        excluded=run(self.port,StructuredQuerySpec(**base),"quant",temporal)
        rejected=run(self.port,StructuredQuerySpec(**base,unknown_availability_policy=UnknownAvailabilityPolicy.REJECT),"quant",temporal)
        self.assertEqual(excluded.status,ChannelStatus.EMPTY);self.assertEqual(rejected.status,ChannelStatus.REJECTED);self.assertIn("unknown_availability",rejected.reason)

    def test_derived_dependency_must_be_eligible_at_cutoff(self):
        spec=StructuredQuerySpec("macro",select_fields=("series_id","value"),predicates=(Predicate("series_id",PredicateOperator.EQ,"DERIVED"),))
        before=run(self.port,spec,"quant",TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2025-01-15T00:00:00Z"))
        after=run(self.port,spec,"quant",TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2025-03-01T00:00:00Z"))
        self.assertEqual(before.status,ChannelStatus.EMPTY);self.assertEqual(after.status,ChannelStatus.OK)

    def test_units_and_nulls_are_preserved(self):
        spec=StructuredQuerySpec("macro",select_fields=("series_id","value"),predicates=(Predicate("series_id",PredicateOperator.EQ,"NULLABLE"),))
        result=run(self.port,spec,"quant");item=result.items[0]
        value=next(f for f in item.fields if f.name=="value")
        self.assertIsNone(value.value);self.assertEqual(value.unit,"index");self.assertEqual(item.null_rules,("null_is_missing",))

    def test_ip_prefix_containment_is_compiled_without_network_extension(self):
        spec=StructuredQuerySpec("prefixes",select_fields=("prefix","owner"),predicates=(Predicate("prefix",PredicateOperator.IP_IN_PREFIX,"192.0.2.42"),))
        result=run(self.port,spec,"networking")
        self.assertEqual(result.status,ChannelStatus.OK);self.assertEqual(result.items[0].fields[0].value,"192.0.2.0/24")

    def test_raw_sql_path_function_and_field_injection_attempts_fail(self):
        raw=asyncio.run(self.port.execute(StructuredRequest("SELECT * FROM read_parquet('/etc/passwd')",scope("quant"),TemporalRequest(TemporalMode.CURRENT),snap())))
        path=run(self.port,StructuredQuerySpec("../../secret.parquet",select_fields=("x",)),"quant")
        self.assertEqual(raw.status,ChannelStatus.REJECTED);self.assertEqual(path.status,ChannelStatus.REJECTED)
        with self.assertRaises(StructuredValidationError):
            StructuredCompiler(self.registry).compile(StructuredQuerySpec("macro",select_fields=('value" FROM macro_fixture; DROP TABLE macro_fixture; --',)),scope("quant"),TemporalRequest(TemporalMode.CURRENT),snap())
        function=StructuredQuerySpec("macro",aggregations=(Aggregation("read_csv","value","x"),))
        self.assertEqual(run(self.port,function,"quant").status,ChannelStatus.REJECTED)

    def test_verified_structured_result_stays_typed_outside_passage_rrf(self):
        result=run(self.port,StructuredQuerySpec("vulnerability",aggregations=(Aggregation(AggregationFunction.COUNT,None,"count"),)),"cybersecurity")
        class Tokenizer:
            name="char";revision="1";fingerprint="char/1"
            def encode(self,text):return tuple(ord(c) for c in text)
            def decode(self,tokens):return "".join(chr(v) for v in tokens)
        plan=SimpleNamespace(budget=SimpleNamespace(max_context_tokens=128),scope=scope("cybersecurity"),snapshot=snap())
        fusion=FusionResult((),(),(result,),(),(),"cfg")
        pack=asyncio.run(ContextPacker(Tokenizer(),None).pack(RerankOutcome(()),fusion,plan,ContextBudget(128,8,8)))
        self.assertEqual(pack.structured_obligations,(result,));self.assertEqual(pack.passages,())

    def test_scan_budget_is_distinct_from_output_limit(self):
        bounded=DuckDBStructuredPort(self.registry,max_scan_rows=50)
        spec=StructuredQuerySpec("vulnerability",aggregations=(Aggregation(AggregationFunction.COUNT,None,"count"),),presentation_limit=1)
        result=run(bounded,spec,"cybersecurity")
        self.assertEqual(result.status,ChannelStatus.UNAVAILABLE);self.assertIn("RuntimeError",result.reason)

if __name__=="__main__":unittest.main()
