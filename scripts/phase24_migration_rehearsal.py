#!/usr/bin/env python3
from __future__ import annotations
import argparse,asyncio,json,os,sys,tempfile
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from cti_rag.composition.feature_flags import RetrievalFeatureFlags
from cti_rag.contracts import AccessLabel,CandidateBudget,ProcessingClass,TemporalMode,TemporalRequest
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.operations import OperationalPaths,RecoveryManager
from cti_rag.ports import EffectiveScope,ProjectionBuildRequest,SearchKind,SearchRequest
from cti_rag.retrieval import SQLiteFTS5LexicalIndex,StructuredJsonProjector
from cti_rag.snapshots import SnapshotCatalogStore,SnapshotPublisher

UTC=timezone.utc

@contextmanager
def env_flag(name,value):
    old=os.environ.get(name)
    if value is None:os.environ.pop(name,None)
    else:os.environ[name]=value
    try:yield
    finally:
        if old is None:os.environ.pop(name,None)
        else:os.environ[name]=old

def build(root):
    paths=OperationalPaths.from_root(root);objects=FileObjectStore(paths.objects)
    meta=CanonicalMetadataStore.sqlite(paths.canonical_db,object_exists=objects.exists)
    catalog=SnapshotCatalogStore.sqlite(paths.catalog_db);publisher=SnapshotPublisher(catalog)
    lexical=SQLiteFTS5LexicalIndex(paths.root/"lexical.sqlite",catalog)
    return paths,objects,meta,catalog,publisher,lexical

def search(lexical,scope,snapshot,query):
    request=SearchRequest(query,SearchKind.LEXICAL,scope,TemporalRequest(TemporalMode.CURRENT),CandidateBudget(20,lexical=20),snapshot)
    return asyncio.run(lexical.search(request))

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--root");p.add_argument("--backup");p.add_argument("--report",required=True);args=p.parse_args(argv)
    owned=None
    if args.root is None:owned=tempfile.TemporaryDirectory();root=Path(owned.name)/"runtime"
    else:root=Path(args.root)
    backup=Path(args.backup) if args.backup else root.parent/"migration-backup"
    paths,objects,meta,catalog,publisher,lexical=build(root)
    scope=EffectiveScope("migration-local","public",("cybersecurity",),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_ONLY,),1)
    projector=StructuredJsonProjector("unicode61/1")

    def generation(gid,revision_uid,term):
        payload=json.dumps({"id":revision_uid,"summary":f"{term} migration evidence"},sort_keys=True).encode()
        _exact,docs=projector.project(normalized_bytes=payload,artifact_uid=f"art-{revision_uid}",revision_uid=revision_uid,object_uid=f"obj-{revision_uid}",namespace="migration",object_type="record",canonical_id=revision_uid,domain="cybersecurity",source_id="phase24-fixture",tenant_id="public",access_label=AccessLabel.PUBLIC,available_at=datetime(2026,9,25,tzinfo=UTC),text_pointers=("/summary",),context_prefix="phase24 migration")
        req=ProjectionBuildRequest(gid,"lexical",(revision_uid,),("unicode61/1",),("lexical",),0)
        return lexical.build(req,docs)

    legacy=generator=generation("phase24-legacy-g1","rev-legacy","legacytoken")
    publisher.stage_generation(legacy);legacy_manifest=publisher.publish((legacy.generation_id,),("lexical",),created_at=datetime(2026,9,25,1,tzinfo=UTC))
    legacy_result=search(lexical,scope,legacy_manifest.to_ref(),"legacytoken")
    with env_flag("CTI_RAG_ADVANCED_RETRIEVAL_ENABLED",None):
        default_flags=RetrievalFeatureFlags.from_env()
    new=generation("phase24-new-g2","rev-new","advancedtoken")
    publisher.stage_generation(new);new_manifest=publisher.publish((new.generation_id,),("lexical",),created_at=datetime(2026,9,25,2,tzinfo=UTC))
    with env_flag("CTI_RAG_ADVANCED_RETRIEVAL_ENABLED","1"):
        switched_flags=RetrievalFeatureFlags.from_env()
    advanced_result=search(lexical,scope,new_manifest.to_ref(),"advancedtoken")

    # Roll back to the already-serviceable legacy generation.
    rolled=publisher.rollback(legacy_manifest.manifest_id)
    rollback_result=search(lexical,scope,rolled.to_ref(),"legacytoken")

    # Re-publish new generation, then tombstone the passage; current revocations must hide it immediately.
    current=publisher.publish((new.generation_id,),("lexical",),created_at=datetime(2026,9,25,3,tzinfo=UTC))
    hit=search(lexical,scope,current.to_ref(),"advancedtoken").items[0]
    catalog.admit_revocation(hit.passage_uid,"phase24 deletion rehearsal",(),("lexical",))
    deleted_result=search(lexical,scope,current.to_ref(),"advancedtoken")

    manager=RecoveryManager(objects,meta,catalog,publisher);manager.create_backup(backup)
    restored_root=root.parent/"restored"
    _p2,objects2,meta2,catalog2,publisher2,_lex2=build(restored_root)
    restored=RecoveryManager(objects2,meta2,catalog2,publisher2);restored.restore_backup(backup)

    report={
      "schema_version":"phase24-migration-rehearsal/1",
      "legacy_default":{"advanced_retrieval_enabled":default_flags.advanced_retrieval_enabled,"legacy_endpoints_enabled":default_flags.legacy_endpoints_enabled,"query_status":legacy_result.status.value,"revision_uid":legacy_result.items[0].revision_uid if legacy_result.items else None},
      "new_generation":{"manifest_id":new_manifest.manifest_id,"query_status":advanced_result.status.value,"revision_uid":advanced_result.items[0].revision_uid if advanced_result.items else None},
      "feature_switch":{"advanced_retrieval_enabled":switched_flags.advanced_retrieval_enabled,"legacy_endpoints_enabled":switched_flags.legacy_endpoints_enabled},
      "rollback":{"manifest_id":rolled.manifest_id,"query_status":rollback_result.status.value,"revision_uid":rollback_result.items[0].revision_uid if rollback_result.items else None},
      "deletion":{"revoked_passage_uid":hit.passage_uid,"query_status_after_revocation":deleted_result.status.value},
      "backup_restore":{"restored_current_manifest_id":catalog2.current_manifest().manifest_id if catalog2.current_manifest() else None,"revocation_preserved":catalog2.is_revoked(hit.passage_uid),"canonical_counts":meta2.counts()},
      "optional_components":{"web_overlay_enabled":default_flags.web_overlay_enabled,"opencti_required_for_core":False,"external_runtimepolicy_required_for_public_local_core":False},
    }
    Path(args.report).write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,sort_keys=True))
    if owned is not None:owned.cleanup()
    return 0
if __name__=="__main__":raise SystemExit(main())
