import tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path

from cti_rag.application.guarded import authorized_search
from cti_rag.contracts import CandidateBudget,CharacterSpanLocator,PassageHit,ProvenanceRef,TemporalMode,TemporalRequest
from cti_rag.policy.local import PublicOnlyLocalPolicy
from cti_rag.ports import AuthenticatedPrincipal,BackendCapabilities,ClientScopeRequest,ScoreDirection,SearchKind
from cti_rag.snapshots import (
    ProjectionGeneration,ProjectionPayload,PublicationError,RevocationAwareEvidenceStore,SnapshotCatalogStore,
    SnapshotPublisher,admit_candidates,
)
from cti_rag.testing import CountingSearchPort

UTC=timezone.utc
NOW=datetime(2026,1,1,tzinfo=UTC)

def generation(kind,gid,revision_uids=("rev-a",),visible=True,ready=True,integrity=True):
    payloads=tuple(ProjectionPayload(f"{kind}:{r}",r,'{"kind":"character_span","start":0,"end":4}',f"digest-{kind}-{r}","text") for r in revision_uids)
    return ProjectionGeneration(
        gid,kind,tuple(sorted(revision_uids)),(f"{kind}/1",),f"checksum-{gid}",ready,visible,integrity,0,(kind,),NOW,payloads
    )

class FakeBuilder:
    def __init__(self): self.cleaned=[]
    def cleanup(self,generation_id): self.cleaned.append(generation_id)

class Phase4SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.catalog=SnapshotCatalogStore.sqlite(Path(self.tmp.name)/"catalog.db")
        self.publisher=SnapshotPublisher(self.catalog)
    def tearDown(self): self.tmp.cleanup()
    def stage_pair(self,suffix,revision_uids=("rev-a",)):
        exact=generation("exact",f"exact-{suffix}",revision_uids)
        lexical=generation("lexical",f"lex-{suffix}",revision_uids)
        self.publisher.stage_generation(exact); self.publisher.stage_generation(lexical)
        return exact,lexical
    def publish_pair(self,suffix,revision_uids=("rev-a",)):
        pair=self.stage_pair(suffix,revision_uids)
        return self.publisher.publish(tuple(g.generation_id for g in pair),("exact","lexical"),created_at=NOW)

    def test_crash_before_pointer_swap_keeps_previous_manifest_serving(self):
        first=self.publish_pair("a")
        pair=self.stage_pair("b")
        with self.assertRaisesRegex(PublicationError,"before_pointer_swap"):
            self.publisher.publish(tuple(g.generation_id for g in pair),("exact","lexical"),created_at=NOW+timedelta(seconds=1),failpoint="before_pointer_swap")
        self.assertEqual(self.catalog.current_manifest().manifest_id,first.manifest_id)

    def test_concurrent_reader_pins_one_coherent_manifest_and_blocks_cleanup(self):
        first=self.publish_pair("a")
        pinned=self.catalog.pin_current(ttl_seconds=60,now=NOW)
        second=self.publish_pair("b")
        self.assertEqual(pinned.manifest.manifest_id,first.manifest_id)
        self.assertEqual(self.catalog.current_manifest().manifest_id,second.manifest_id)
        self.assertTrue(self.catalog.generation_in_use("exact-a",NOW+timedelta(seconds=1)))
        self.assertFalse(self.catalog.cleanup_generation("exact-a",NOW+timedelta(seconds=1)))
        self.catalog.release_lease(pinned.lease_id)
        self.assertTrue(self.catalog.cleanup_generation("exact-a",NOW+timedelta(seconds=1)))

    def test_missing_serving_visibility_or_integrity_cannot_publish(self):
        good=generation("exact","exact-good")
        hidden=generation("lexical","lex-hidden",visible=False)
        self.publisher.stage_generation(good); self.publisher.stage_generation(hidden)
        with self.assertRaisesRegex(PublicationError,"serving-visible"):
            self.publisher.publish(("exact-good","lex-hidden"),("exact","lexical"),created_at=NOW)

    def test_incompatible_projection_revision_sets_cannot_publish(self):
        exact=generation("exact","exact-mismatch",("rev-a",))
        graph=generation("graph","graph-mismatch",("rev-b",))
        self.publisher.stage_generation(exact); self.publisher.stage_generation(graph)
        with self.assertRaisesRegex(PublicationError,"revision sets"):
            self.publisher.publish(("exact-mismatch","graph-mismatch"),("exact","graph"),created_at=NOW)

    def test_snapshot_required_backend_is_not_called_without_pinned_snapshot(self):
        backend=CountingSearchPort(BackendCapabilities(
            supported_filters=frozenset({"tenant","domain","access_label"}),
            snapshot_support=True,requires_snapshot=True,score_direction=ScoreDirection.HIGHER_IS_BETTER,
        ))
        result=__import__("asyncio").run(authorized_search(
            policy=PublicOnlyLocalPolicy.build("public-user"),
            principal=AuthenticatedPrincipal("public-user","public"),
            client_scope=ClientScopeRequest(("cybersecurity",)),
            backend=backend,query="x",kind=SearchKind.LEXICAL,
            temporal=TemporalRequest(TemporalMode.CURRENT),budget=CandidateBudget(5),snapshot=None,
        ))
        self.assertEqual(result.status.value,"rejected")
        self.assertEqual(backend.calls,0)

    def test_revocation_aware_hydration_denies_old_revision(self):
        class Store:
            def get_revision(self,uid): return {"revision_uid":uid}
            def get_artifact(self,uid): return None
            def get_passage(self,uid): return None
            def resolve(self,ref): return b"payload"
            def dependents(self,uid): return ()
        wrapped=RevocationAwareEvidenceStore(Store(),self.catalog)
        self.assertEqual(wrapped.get_revision("rev-a")["revision_uid"],"rev-a")
        self.catalog.admit_revocation("rev-a","withdrawn")
        self.assertIsNone(wrapped.get_revision("rev-a"))
        self.assertIsNone(wrapped.resolve(ProvenanceRef("rev-a",CharacterSpanLocator(0,4))))

    def test_failed_publication_retry_is_idempotent(self):
        pair=self.stage_pair("retry")
        first=self.publisher.publish(tuple(g.generation_id for g in pair),("exact","lexical"),created_at=NOW)
        second=self.publisher.publish(tuple(g.generation_id for g in pair),("exact","lexical"),created_at=NOW+timedelta(days=1))
        self.assertEqual(first.manifest_id,second.manifest_id)
        self.assertEqual(self.catalog.current_manifest().manifest_id,first.manifest_id)

    def test_revocation_overlay_blocks_candidate_from_old_snapshot_immediately(self):
        manifest=self.publish_pair("a")
        pinned=self.catalog.pin_current(ttl_seconds=60,now=NOW)
        hit=PassageHit("hit","passage-a","rev-a",ProvenanceRef("rev-a",CharacterSpanLocator(0,4)),"text")
        self.assertEqual(admit_candidates(self.catalog,(hit,)),(hit,))
        self.catalog.admit_revocation("rev-a","withdrawn",(),("exact","lexical","dense","graph","structured","derived"))
        self.assertEqual(admit_candidates(self.catalog,(hit,)),())
        self.assertEqual(pinned.manifest.manifest_id,manifest.manifest_id)
        self.assertTrue(self.catalog.pending_invalidations())
        cleanup=self.catalog.pending_cleanup("rev-a")
        self.assertEqual({row[2] for row in cleanup},{"exact","lexical","dense","graph","structured","derived"})
        for event_id,_,_ in self.catalog.pending_invalidations(): self.catalog.ack_invalidation(event_id)
        for task_id,_,_ in cleanup: self.catalog.ack_cleanup(task_id,NOW)
        self.assertEqual(self.catalog.pending_invalidations(),())
        self.assertEqual(self.catalog.pending_cleanup("rev-a"),())

    def test_backup_restore_reproduces_manifest_and_citable_payloads(self):
        manifest=self.publish_pair("backup")
        self.catalog.admit_revocation("rev-z","policy",(),("exact",))
        backup=self.catalog.backup_json()
        restored=SnapshotCatalogStore.sqlite(Path(self.tmp.name)/"restored.db")
        restored.restore_json(backup)
        self.assertEqual(restored.current_manifest(),manifest)
        for binding in manifest.projections:
            self.assertEqual(restored.get_generation(binding.generation_id),self.catalog.get_generation(binding.generation_id))
        self.assertTrue(restored.is_revoked("rev-z"))

    def test_failed_generation_cleanup_and_expired_lease_recovery(self):
        failed=generation("dense","dense-failed")
        self.publisher.stage_generation(failed); self.catalog.mark_generation_failed(failed.generation_id)
        builder=FakeBuilder()
        self.assertTrue(self.publisher.cleanup_failed(failed.generation_id,builder))
        self.assertEqual(builder.cleaned,["dense-failed"])
        self.assertIsNone(self.catalog.get_generation("dense-failed"))
        old=self.publish_pair("lease")
        pin=self.catalog.pin_current(ttl_seconds=1,now=NOW)
        new=self.publish_pair("after-lease")
        self.assertNotEqual(old.manifest_id,new.manifest_id)
        self.assertTrue(self.catalog.generation_in_use("exact-lease",NOW))
        self.catalog.cleanup_expired_leases(NOW+timedelta(seconds=2))
        self.assertFalse(self.catalog.generation_in_use("exact-lease",NOW+timedelta(seconds=2)))
        self.assertTrue(self.catalog.cleanup_generation("exact-lease",NOW+timedelta(seconds=2)))
        self.assertEqual(pin.manifest.manifest_id,old.manifest_id)

if __name__=="__main__": unittest.main()
