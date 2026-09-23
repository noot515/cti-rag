import asyncio,json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path

from cti_rag.contracts import AccessLabel,CandidateBudget,ProcessingClass,SnapshotManifestRef,TemporalMode,TemporalRequest
from cti_rag.domains.networking import (
    RFC_MANIFEST,BGP_MANIFEST,RPKI_MANIFEST,DNS_MANIFEST,RDAP_MANIFEST,RFC_1771_XML,RFC_4271_XML,BGP_FIXTURE,BGP_CORRECTED_FIXTURE,
    RfcConnector,BgpConnector,RpkiConnector,DnsConnector,RdapConnector,RfcNormalizer,BgpNormalizer,RpkiNormalizer,DnsNormalizer,RdapNormalizer,
    NetworkingProjectionRebuilder,networking_dataset_registry,networking_source_coverage,NetworkingSourceStatus,
    export_source_records,import_source_records,replay_normalized,
)
from cti_rag.graph import EntityResolutionJournal,ReferenceGraphPort,TraversalStep,TraversalTemplate
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.ingestion import IngestionPipeline
from cti_rag.ports import ChannelStatus,EffectiveScope,GraphRequest,ProjectionBuildRequest,SearchKind,SearchRequest,StructuredRequest
from cti_rag.retrieval import ExactLookupRequest,ExactLookupStatus,PersistentExactIndex,SQLiteFTS5LexicalIndex
from cti_rag.snapshots import SnapshotCatalogStore,SnapshotPublisher
from cti_rag.structured import DuckDBStructuredPort,Predicate,PredicateOperator,StructuredQuerySpec

UTC=timezone.utc
NOW=datetime(2026,3,1,tzinfo=UTC)
SCOPE=EffectiveScope("alice","public",("networking",),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_ONLY,),1)

class SupportStore:
    def __init__(self,revisions):self.revisions=set(revisions)
    def resolve(self,ref):return b"supported" if ref.revision_uid in self.revisions else None
    def get_revision(self,uid):return None
    def get_artifact(self,uid):return None
    def get_passage(self,uid):return None
    def dependents(self,uid):return ()

def runtime(td):
    root=Path(td);objects=FileObjectStore(root/"objects");meta=CanonicalMetadataStore.sqlite(root/"meta.db",object_exists=objects.exists);catalog=SnapshotCatalogStore.sqlite(root/"catalog.db")
    return objects,meta,catalog

async def ingest_all(pipeline):
    cursor=None;accepted=0;quarantined=0
    while True:
        result=await pipeline.ingest_page(cursor);accepted+=result["accepted"];quarantined+=result["quarantined"]
        if result["exhausted"]:return accepted,quarantined
        cursor=result["next_cursor"]

def field(result,name):
    return next(f.value for f in result.items[0].fields if f.name==name)

class Phase12NetworkingTests(unittest.TestCase):
    def test_source_normalizers_manifest_metadata_and_coverage_are_explicit(self):
        rfc=RfcNormalizer().normalize(asyncio.run(RfcConnector((RFC_4271_XML,)).fetch_page(None)).records[0])
        body=json.loads(rfc.normalized_bytes);self.assertEqual(body["id"],"RFC 4271");self.assertEqual(body["obsoletes"],["RFC 1771"]);self.assertEqual(body["sections"][1]["number"],"4.3")
        bgp=BgpNormalizer().normalize(asyncio.run(BgpConnector((BGP_FIXTURE[0],)).fetch_page(None)).records[0]);b=json.loads(bgp.normalized_bytes)
        self.assertEqual((b["prefix_family"],b["prefix_length"],b["origin_asn"]),(4,24,"AS64500"))
        self.assertEqual(len(b["prefix_start"]),32);self.assertEqual(len(b["prefix_end"]),32)
        rpki=RpkiNormalizer().normalize(asyncio.run(RpkiConnector().fetch_page(None)).records[0]);self.assertEqual(json.loads(rpki.normalized_bytes)["max_length"],25)
        dns=DnsNormalizer().normalize(asyncio.run(DnsConnector().fetch_page(None)).records[0]);self.assertEqual(json.loads(dns.normalized_bytes)["ttl"],300)
        rdap=RdapNormalizer().normalize(asyncio.run(RdapConnector().fetch_page(None)).records[0]);self.assertEqual(json.loads(rdap.normalized_bytes)["entity_handle"],"EXAMPLE-NET")
        for manifest in (RFC_MANIFEST,BGP_MANIFEST,RPKI_MANIFEST,DNS_MANIFEST,RDAP_MANIFEST):
            self.assertTrue(manifest.source_id and manifest.format and manifest.connector_fingerprint and manifest.parser_fingerprint and manifest.license_notice)
        coverage={x.source_id:x for x in networking_source_coverage()}
        for sid in ("rfc-editor","ripe-ris-fixture","rpki-roa-fixture","dns-observation-fixture","rdap-registration-fixture"):
            self.assertEqual(coverage[sid].status,NetworkingSourceStatus.FIXTURE_VALIDATED)
        for sid in ("rir-bulk-registration","network-configurations","packet-event-metadata","certificate-observations","network-topology"):
            self.assertEqual(coverage[sid].status,NetworkingSourceStatus.DEFERRED);self.assertTrue(coverage[sid].reason)

    def test_rfc_exact_obsolete_status_and_section_locator(self):
        with tempfile.TemporaryDirectory() as td:
            objects,meta,catalog=runtime(td)
            asyncio.run(ingest_all(IngestionPipeline(RFC_MANIFEST,RfcConnector(),RfcNormalizer(),objects,meta)))
            bundle=NetworkingProjectionRebuilder(meta,objects).rebuild(("rfc-editor",),"rfc-manifest")
            revisions=tuple(sorted({x.revision_uid for x in bundle.exact}))
            exact=PersistentExactIndex.sqlite(Path(td)/"exact.db",catalog);lex=SQLiteFTS5LexicalIndex(Path(td)/"lex.db",catalog)
            eg=exact.build(ProjectionBuildRequest("rfc-exact","exact",revisions,("canonical/1",),("exact",)),bundle.exact)
            lg=lex.build(ProjectionBuildRequest("rfc-lex","lexical",revisions,("unicode61/1",),("lexical",)),bundle.lexical)
            pub=SnapshotPublisher(catalog);pub.stage_generation(eg);pub.stage_generation(lg);manifest=pub.publish(("rfc-exact","rfc-lex"),("exact","lexical"),created_at=NOW);snap=manifest.to_ref()
            old=exact.lookup(ExactLookupRequest("RFC 1771",SCOPE,TemporalRequest(TemporalMode.CURRENT),snap))
            self.assertEqual(old.status,ExactLookupStatus.FOUND);self.assertIn("obsoleted by RFC 4271",old.records[0].original_text)
            result=asyncio.run(lex.search(SearchRequest("transfer routing information",SearchKind.LEXICAL,SCOPE,TemporalRequest(TemporalMode.CURRENT),CandidateBudget(10,lexical=10),snap)))
            self.assertEqual(result.status,ChannelStatus.OK)
            hit=next(x for x in result.items if "transfer routing information" in x.text)
            self.assertEqual(hit.provenance.locator.scheme,"rfc-section");self.assertEqual(hit.provenance.locator.value,"RFC 4271#4.3")

    def test_ipv4_ipv6_longest_prefix_missing_and_collector_disagreement(self):
        with tempfile.TemporaryDirectory() as td:
            objects,meta,_catalog=runtime(td)
            for manifest,connector,normalizer in ((BGP_MANIFEST,BgpConnector(),BgpNormalizer()),(RPKI_MANIFEST,RpkiConnector(),RpkiNormalizer()),(DNS_MANIFEST,DnsConnector(),DnsNormalizer()),(RDAP_MANIFEST,RdapConnector(),RdapNormalizer())):
                asyncio.run(ingest_all(IngestionPipeline(manifest,connector,normalizer,objects,meta)))
            bundle=NetworkingProjectionRebuilder(meta,objects).rebuild(system_manifest_id="network-manifest")
            port=DuckDBStructuredPort(networking_dataset_registry(bundle.structured_rows));snap=SnapshotManifestRef("network-manifest","corpus",NOW,("structured-g",))
            def run_ip(addr):
                spec=StructuredQuerySpec("network_bgp",select_fields=("prefix","prefix_length","origin_asn","collector"),predicates=(Predicate("prefix",PredicateOperator.IP_IN_PREFIX,addr),),order_by=(("prefix_length","desc"),),presentation_limit=1)
                return asyncio.run(port.execute(StructuredRequest(spec,SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)))
            v4=run_ip("203.0.113.200");self.assertEqual(v4.status,ChannelStatus.OK);self.assertEqual(field(v4,"prefix"),"203.0.113.128/25")
            v6=run_ip("2001:db8:1::1234");self.assertEqual(v6.status,ChannelStatus.OK);self.assertEqual(field(v6,"prefix"),"2001:db8:1::/48")
            missing=run_ip("192.0.2.10");self.assertEqual(missing.status,ChannelStatus.EMPTY)
            spec=StructuredQuerySpec("network_bgp",select_fields=("collector","origin_asn"),predicates=(Predicate("prefix",PredicateOperator.EQ,"203.0.113.0/24"),Predicate("observation_start",PredicateOperator.EQ,"2026-01-10T00:00:00Z")),order_by=(("collector","asc"),))
            disagree=asyncio.run(port.execute(StructuredRequest(spec,SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)))
            self.assertEqual(disagree.status,ChannelStatus.OK);self.assertEqual(set(field(disagree,"origin_asn")),{"AS64500","AS64501"})

    def test_historical_dns_bgp_and_safe_correction_do_not_leak_future_observations(self):
        with tempfile.TemporaryDirectory() as td:
            objects,meta,_catalog=runtime(td)
            asyncio.run(ingest_all(IngestionPipeline(BGP_MANIFEST,BgpConnector((BGP_FIXTURE[0],BGP_FIXTURE[-1])),BgpNormalizer(),objects,meta)))
            asyncio.run(ingest_all(IngestionPipeline(BGP_MANIFEST,BgpConnector(BGP_CORRECTED_FIXTURE),BgpNormalizer(),objects,meta)))
            asyncio.run(ingest_all(IngestionPipeline(DNS_MANIFEST,DnsConnector(),DnsNormalizer(),objects,meta)))
            self.assertEqual(len(meta.revision_uids_for_source_object(BGP_MANIFEST.source_id,BGP_FIXTURE[0]["id"])),2)
            bundle=NetworkingProjectionRebuilder(meta,objects).rebuild((BGP_MANIFEST.source_id,DNS_MANIFEST.source_id),"network-manifest")
            port=DuckDBStructuredPort(networking_dataset_registry(bundle.structured_rows));snap=SnapshotManifestRef("network-manifest","c",NOW,("structured-g",))
            bgp_spec=StructuredQuerySpec("network_bgp",select_fields=("origin_asn","available_at"),predicates=(Predicate("prefix",PredicateOperator.EQ,"203.0.113.0/24"),Predicate("collector",PredicateOperator.EQ,"rrc00")))
            historical=asyncio.run(port.execute(StructuredRequest(bgp_spec,SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-15T00:00:00Z"),snap)))
            current=asyncio.run(port.execute(StructuredRequest(bgp_spec,SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)))
            self.assertEqual(field(historical,"origin_asn"),"AS64500");self.assertEqual(field(current,"origin_asn"),"AS64509")
            late_spec=StructuredQuerySpec("network_bgp",select_fields=("prefix",),predicates=(Predicate("prefix",PredicateOperator.EQ,"198.51.100.0/24"),))
            self.assertEqual(asyncio.run(port.execute(StructuredRequest(late_spec,SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-15T00:00:00Z"),snap))).status,ChannelStatus.EMPTY)
            dns_spec=StructuredQuerySpec("network_dns",select_fields=("rdata","observed_at"),predicates=(Predicate("qname",PredicateOperator.EQ,"example.test"),Predicate("rrtype",PredicateOperator.EQ,"A")))
            dns=asyncio.run(port.execute(StructuredRequest(dns_spec,SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-15T00:00:00Z"),snap)))
            self.assertEqual(field(dns,"rdata"),"203.0.113.7")

    def test_graph_distinguishes_announcement_registration_and_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            objects,meta,catalog=runtime(td)
            for manifest,connector,normalizer in ((BGP_MANIFEST,BgpConnector(BGP_FIXTURE[:3]),BgpNormalizer()),(RPKI_MANIFEST,RpkiConnector(),RpkiNormalizer()),(RDAP_MANIFEST,RdapConnector(),RdapNormalizer())):
                asyncio.run(ingest_all(IngestionPipeline(manifest,connector,normalizer,objects,meta)))
            bundle=NetworkingProjectionRebuilder(meta,objects).rebuild((BGP_MANIFEST.source_id,RPKI_MANIFEST.source_id,RDAP_MANIFEST.source_id),"network-graph")
            revisions=tuple(sorted({a.revision_uid for a in bundle.assertions}))
            template=TraversalTemplate("network-relations",(
                TraversalStep("announced_by",("prefix",),("asn",)),
                TraversalStep("authorized_origin",("prefix",),("asn",)),
                TraversalStep("registered_to",("prefix",),("legal-entity",)),
            ))
            port=ReferenceGraphPort(catalog,SupportStore(revisions),(template,),EntityResolutionJournal(bundle.entities))
            generation=port.build(ProjectionBuildRequest("network-graph-g","graph",revisions,("graph/1",),("graph",)),bundle.entities,bundle.assertions)
            pub=SnapshotPublisher(catalog);pub.stage_generation(generation);manifest=pub.publish(("network-graph-g",),("graph",),created_at=NOW)
            prefix=next(e for e in bundle.entities if e.entity_type=="prefix" and e.identifier=="203.0.113.0/24")
            temporal=TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-10T00:30:00Z")
            async def relation(name):
                return await port.traverse(GraphRequest((prefix.entity_uid,),(name,),SCOPE,temporal,1,20,manifest.to_ref(),template_id="network-relations"))
            ann=asyncio.run(relation("announced_by"));auth=asyncio.run(relation("authorized_origin"));reg=asyncio.run(relation("registered_to"))
            self.assertEqual(set(p.node_uids[-1] for p in ann.items),{e.entity_uid for e in bundle.entities if e.entity_type=="asn" and e.identifier in ("AS64500","AS64501")})
            self.assertEqual({p.relation_types for p in auth.items},{("authorized_origin",)});self.assertEqual({p.relation_types for p in reg.items},{("registered_to",)})
            self.assertTrue(all("ownership" not in p.semantics for p in ann.items+auth.items+reg.items))

    def test_network_snapshot_export_import_and_replay_are_content_stable(self):
        page=asyncio.run(BgpConnector(BGP_FIXTURE[:2]).fetch_page(None))
        blob=export_source_records(BGP_MANIFEST.source_id,page.records);source_id,records=import_source_records(blob)
        self.assertEqual(source_id,BGP_MANIFEST.source_id);self.assertEqual(tuple(r.raw_bytes for r in records),tuple(r.raw_bytes for r in page.records))
        replay=replay_normalized(records,BgpNormalizer());self.assertEqual(tuple(x.stable_upstream_id for x in replay),tuple(x["id"] for x in BGP_FIXTURE[:2]))
        bad=bytearray(blob);bad[-2]=ord("0") if bad[-2]!=ord("0") else ord("1")
        with self.assertRaises(Exception):import_source_records(bytes(bad))

if __name__=="__main__":unittest.main()
