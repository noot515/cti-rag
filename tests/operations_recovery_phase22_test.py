from __future__ import annotations
import asyncio,json,re,subprocess,sys,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path

from cti_rag.domains.cybersecurity import ATTACK_MANIFEST,AttackStixConnector,AttackStixNormalizer
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.ingestion import IngestionPipeline
from cti_rag.operations import (
    BoundedScheduler,CacheBundle,CacheIdentity,CacheState,CancellationToken,ConcurrentMemoryWindow,
    MemoryProbe,OperationalPaths,ProtectedDebugTraceStore,QueueFull,RecoveryManager,TelemetryRecorder,
    WorkItem,WorkLane,freshness_status,load_profile,scheduler_from_profile,
)
from cti_rag.snapshots import ProjectionGeneration,ProjectionPayload,SnapshotCatalogStore,SnapshotPublisher

ROOT=Path(__file__).resolve().parents[1]
PROFILES=ROOT/"deploy"/"profiles"

def cache_identity(epoch="1",kind="query"):
    return CacheIdentity("principal:tenant:private","scope-hash",str(epoch),"normalized query",("CVE-2099-0001",),"manifest-1","current",None,"plan-1","config-1",("model-1",),"en-US",kind)

async def ingest_attack(meta,objects):
    pipeline=IngestionPipeline(ATTACK_MANIFEST,AttackStixConnector(page_size=1),AttackStixNormalizer(),objects,meta)
    cursor=None
    while True:
        result=await pipeline.ingest_page(cursor)
        if result["exhausted"]:return result
        cursor=result["next_cursor"]

def build_runtime(root):
    paths=OperationalPaths.from_root(root);objects=FileObjectStore(paths.objects);meta=CanonicalMetadataStore.sqlite(paths.canonical_db,object_exists=objects.exists);catalog=SnapshotCatalogStore.sqlite(paths.catalog_db);publisher=SnapshotPublisher(catalog)
    return paths,objects,meta,catalog,publisher

class Phase22OperationsRecoveryTest(unittest.TestCase):
    def test_profiles_expose_only_api_use_configurable_root_and_named_secrets(self):
        loaded={name:load_profile(PROFILES/f"{name}.json") for name in ("fixture","text-mvp","analytical","full-research")}
        for profile in loaded.values():
            self.assertEqual("CTI_RAG_DATA_ROOT",profile.data_root_env)
            self.assertTrue(profile.internal_network)
            self.assertTrue(all(port.startswith("api:") for port in profile.exposed_ports))
            self.assertTrue(all("=" not in secret for secret in profile.secret_names))
            self.assertTrue(profile.service_egress)
            self.assertTrue(all(target.startswith("/") for _service,_source,target in profile.read_only_mounts))
            self.assertIn(("api",("ALL",)),profile.capability_drop)
            limits=dict(profile.scheduler_limits);self.assertGreater(limits["interactive_capacity"],0);self.assertGreater(limits["ingestion_capacity"],0);self.assertGreater(limits["interactive_burst"],0)
        self.assertEqual("deny_all",loaded["fixture"].egress_policy)
        self.assertEqual("allowlist",loaded["full-research"].egress_policy)
        self.assertIn("opencti",loaded["full-research"].egress_allowlist)
        compose=(ROOT/"docker-compose.yml").read_text(encoding="utf-8")
        service_names=set(re.findall(r"^  ([A-Za-z0-9_.-]+):\s*$",compose,re.MULTILINE))
        for name,profile in loaded.items():
            self.assertTrue(set(profile.compose_services).issubset(service_names),name)
        self.assertEqual((),loaded["fixture"].compose_services)
        self.assertIn("threatrag",loaded["text-mvp"].compose_services)
        self.assertIn("neo4j",loaded["analytical"].compose_services)

    def test_profile_smoke_uses_isolated_fixture_storage(self):
        with tempfile.TemporaryDirectory() as td:
            proc=subprocess.run([sys.executable,str(ROOT/"scripts"/"phase22_profile_smoke.py"),"--profile",str(PROFILES/"fixture.json"),"--root",str(Path(td)/"isolated")],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(0,proc.returncode,proc.stderr);report=json.loads(proc.stdout)
            self.assertEqual("fixture",report["profile"]);self.assertEqual(["api:8000"],report["exposed_ports"])
            self.assertEqual(4,len(report["cache_files"]));self.assertEqual({"interactive":0,"ingestion":0},report["scheduler_sizes"])
            text_proc=subprocess.run([sys.executable,str(ROOT/"scripts"/"phase22_profile_smoke.py"),"--profile",str(PROFILES/"text-mvp.json"),"--root",str(Path(td)/"text-mvp-staging")],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(0,text_proc.returncode,text_proc.stderr);text_report=json.loads(text_proc.stdout);self.assertEqual("text-mvp",text_report["profile"])
            self.assertEqual(32,text_report["scheduler_limits"]["interactive_capacity"]);self.assertEqual(64,text_report["scheduler_limits"]["ingestion_capacity"])

    def test_cache_identity_epoch_private_separation_negative_states_and_revocation(self):
        with tempfile.TemporaryDirectory() as td:
            now=[100.0];bundle=CacheBundle(td,clock=lambda:now[0]);private=bundle.store("query",True);public=bundle.store("query",False)
            ident=cache_identity("1");private.put(ident,{"uids":["rev-1"]},ttl_seconds=1000,target_uids=("rev-1",))
            self.assertEqual(CacheState.VALUE,private.get(ident).state);self.assertEqual(CacheState.MISS,public.get(ident).state)
            self.assertEqual(CacheState.MISS,private.get(cache_identity("2")).state)
            self.assertEqual(CacheState.MISS,private.get(ident,revoked=lambda uid:uid=="rev-1").state)
            empty=cache_identity("1","embedding");store=bundle.store("embedding",True);store.put_empty(empty,ttl_seconds=30)
            self.assertEqual(CacheState.EMPTY,store.get(empty).state)
            failed=replace_cache(empty,normalized_query="other");store.put_failed(failed,"backend unavailable",ttl_seconds=3)
            self.assertEqual(CacheState.FAILED,store.get(failed).state);self.assertEqual("backend unavailable",store.get(failed).reason)

    def test_revocation_invalidation_is_independent_of_ttl(self):
        with tempfile.TemporaryDirectory() as td:
            paths,objects,meta,catalog,publisher=build_runtime(Path(td)/"runtime");cache=CacheBundle(paths.cache_root).store("query",False)
            ident=replace_cache(cache_identity(),principal_security_namespace="public:public",normalized_query="q");cache.put(ident,{"value":1},ttl_seconds=86400,target_uids=("rev-x",))
            catalog.admit_revocation("rev-x","withdrawn",projection_kinds=("lexical",));manager=RecoveryManager(objects,meta,catalog,publisher);cleaned=[]
            result=manager.propagate_tombstones(cache.invalidate_target,lambda kind,uid:cleaned.append((kind,uid)))
            self.assertEqual(1,result["invalidations"]);self.assertEqual(1,result["cleanup_tasks"]);self.assertEqual(0,cache.count());self.assertEqual([("lexical","rev-x")],cleaned)

    def test_scheduler_is_bounded_prioritizes_interactive_with_fairness_and_cancels(self):
        scheduler=BoundedScheduler(interactive_capacity=3,ingestion_capacity=1,interactive_burst=2,clock=lambda:10.0)
        for name in ("i1","i2","i3"):scheduler.enqueue(WorkItem(name,WorkLane.INTERACTIVE,lambda token:"ok",enqueued_at=9.0))
        scheduler.enqueue(WorkItem("b1",WorkLane.INGESTION,lambda token:"bulk",enqueued_at=9.0))
        with self.assertRaises(QueueFull):scheduler.enqueue(WorkItem("b2",WorkLane.INGESTION,lambda token:"bulk"))
        self.assertEqual(["i1","i2","b1"],[scheduler.pop_next().request_id for _ in range(3)])
        token=CancellationToken();scheduler2=BoundedScheduler();scheduler2.enqueue(WorkItem("cancel-me",WorkLane.INTERACTIVE,lambda t:"never",token))
        self.assertEqual(1,scheduler2.cancel("cancel-me"));self.assertIsNone(scheduler2.pop_next())

    def test_default_telemetry_excludes_raw_private_values_and_debug_trace_is_protected(self):
        recorder=TelemetryRecorder();secret="PRIVATE QUERY token=super-secret"
        event=recorder.record("retrieve",query=secret,request_id="r1",fields={"candidate_count":4,"latency_ms":12.0,"snippet":secret,"credential":secret})
        payload=recorder.export_json();self.assertNotIn(secret,payload);self.assertNotIn("snippet",payload);self.assertEqual(64,len(event["query_digest"]))
        traces=ProtectedDebugTraceStore()
        with self.assertRaises(PermissionError):traces.put({"query":secret},authorized=False)
        self.assertEqual(1,traces.put({"query":secret},authorized=True))
        memory=ConcurrentMemoryWindow(MemoryProbe(gpu_sampler=lambda:321.0));self.assertIsNone(memory.record(("generation",)))
        memory.record(("generation","reranking"));self.assertEqual(321.0,memory.report()["peak_vram_mb"])
        manifest=type("M",(),{"manifest_id":"m1","created_at":datetime(2026,1,1,tzinfo=timezone.utc)})()
        generation=type("G",(),{"kind":"lexical","ready":True,"visible":True,"referential_integrity":True})()
        fresh=freshness_status(manifest,(generation,),datetime(2026,1,1,0,1,tzinfo=timezone.utc));self.assertEqual(60.0,fresh["freshness_lag_seconds"]);self.assertEqual((("lexical",True,True,True),),fresh["projections"])


    def test_recovery_cli_commands_are_executable_on_isolated_storage(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);root=td/"runtime";backup=td/"backup";restored=td/"restored"
            init=subprocess.run([sys.executable,str(ROOT/"scripts"/"phase22_profile_smoke.py"),"--profile",str(PROFILES/"fixture.json"),"--root",str(root)],cwd=ROOT,text=True,capture_output=True);self.assertEqual(0,init.returncode,init.stderr)
            health=subprocess.run([sys.executable,str(ROOT/"scripts"/"phase22_recovery.py"),"health","--root",str(root)],cwd=ROOT,text=True,capture_output=True);self.assertEqual(0,health.returncode,health.stderr);self.assertIn("canonical_counts",json.loads(health.stdout))
            save=subprocess.run([sys.executable,str(ROOT/"scripts"/"phase22_recovery.py"),"backup","--root",str(root),"--backup",str(backup)],cwd=ROOT,text=True,capture_output=True);self.assertEqual(0,save.returncode,save.stderr)
            load=subprocess.run([sys.executable,str(ROOT/"scripts"/"phase22_recovery.py"),"restore","--root",str(restored),"--backup",str(backup)],cwd=ROOT,text=True,capture_output=True);self.assertEqual(0,load.returncode,load.stderr)
            verify=subprocess.run([sys.executable,str(ROOT/"scripts"/"phase22_recovery.py"),"health","--root",str(restored)],cwd=ROOT,text=True,capture_output=True);self.assertEqual(0,verify.returncode,verify.stderr)

    def test_restart_backup_restore_rebuild_and_rollback_preserve_identity(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);root1=td/"runtime1";paths,objects,meta,catalog,publisher=build_runtime(root1)
            asyncio.run(ingest_attack(meta,objects));checkpoint=meta.checkpoint(ATTACK_MANIFEST.source_id);self.assertIsNotNone(checkpoint)
            revs=tuple(sorted({row[1] for row in meta.projection_artifacts()}));self.assertTrue(revs)
            payload=ProjectionPayload("payload-fixture",revs[0],json.dumps({"kind":"fixture","start":0,"end":1},sort_keys=True),"text-digest")
            now=datetime.now(timezone.utc)
            g1=ProjectionGeneration("phase22-gen-1","lexical",revs,("fixture/1",),"checksum-1",True,True,True,0,("lexical",),now,(payload,))
            publisher.stage_generation(g1);m1=publisher.publish((g1.generation_id,),("lexical",),created_at=now)
            g2=ProjectionGeneration("phase22-gen-2","lexical",revs,("fixture/2",),"checksum-2",True,True,True,0,("lexical",),now,(payload,))
            publisher.stage_generation(g2);m2=publisher.publish((g2.generation_id,),("lexical",),created_at=now)
            # Restart over the same persistent files retains checkpoint and current pointer.
            _p2,_o2,meta_restart,catalog_restart,_pub2=build_runtime(root1)
            self.assertEqual(checkpoint,meta_restart.checkpoint(ATTACK_MANIFEST.source_id));self.assertEqual(m2.manifest_id,catalog_restart.current_manifest().manifest_id)
            manager=RecoveryManager(objects,meta,catalog,publisher);backup=td/"backup";created=manager.create_backup(backup);self.assertEqual(m2.manifest_id,created["current_manifest_id"])
            _paths3,objects3,meta3,catalog3,publisher3=build_runtime(td/"restored");restored=RecoveryManager(objects3,meta3,catalog3,publisher3);restored.restore_backup(backup)
            self.assertEqual(meta.counts(),meta3.counts());self.assertEqual(m2.manifest_id,catalog3.current_manifest().manifest_id)
            self.assertEqual(checkpoint,meta3.checkpoint(ATTACK_MANIFEST.source_id))
            rebuilt=restored.rebuild_fixture_index(td/"restored"/"rebuilt.json")
            self.assertEqual(m2.manifest_id,rebuilt["manifest_id"]);self.assertEqual(revs,tuple(rebuilt["projections"][0]["revision_uids"]))
            self.assertEqual("payload-fixture",rebuilt["projections"][0]["payloads"][0]["payload_uid"])
            rebuilt_payload=rebuilt["projections"][0]["payloads"][0];self.assertEqual(json.dumps({"kind":"fixture","start":0,"end":1},sort_keys=True),rebuilt_payload["locator_json"]);self.assertEqual("text-digest",rebuilt_payload["text_digest"])
            rolled=restored.rollback(m1.manifest_id);self.assertEqual(m1.manifest_id,rolled.manifest_id);self.assertEqual(m1.manifest_id,catalog3.current_manifest().manifest_id)

def replace_cache(identity,**changes):
    values={
        "principal_security_namespace":identity.principal_security_namespace,"effective_scope_hash":identity.effective_scope_hash,
        "policy_epoch":identity.policy_epoch,"normalized_query":identity.normalized_query,"exact_identifiers":identity.exact_identifiers,
        "snapshot_id":identity.snapshot_id,"temporal_mode":identity.temporal_mode,"temporal_cutoff":identity.temporal_cutoff,
        "plan_fingerprint":identity.plan_fingerprint,"config_fingerprint":identity.config_fingerprint,
        "model_fingerprints":identity.model_fingerprints,"locale":identity.locale,"cache_kind":identity.cache_kind,
    }
    values.update(changes);return CacheIdentity(**values)

if __name__=="__main__":unittest.main()
