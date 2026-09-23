#!/usr/bin/env python3
"""Offline-first core cyber source lifecycle commands. Live network access is intentionally not implicit."""
import argparse,asyncio,json
from pathlib import Path
from cti_rag.domains.cybersecurity import (
    ATTACK_MANIFEST,CVE_MANIFEST,KEV_MANIFEST,ATTACK_STIX_REVOKED_FIXTURE,CVE_V5_UPDATED_FIXTURE,
    AttackStixConnector,AttackStixNormalizer,CveListConnector,CveJsonV5Normalizer,KevConnector,KevNormalizer,
    CyberProjectionRebuilder,CyberSourceLifecycle,source_coverage_matrix
)
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.ingestion import IngestionPipeline
from cti_rag.snapshots import RevocationCoordinator,SnapshotCatalogStore

SOURCES={
 "attack":(ATTACK_MANIFEST,AttackStixConnector,AttackStixNormalizer),
 "cve":(CVE_MANIFEST,CveListConnector,CveJsonV5Normalizer),
 "kev":(KEV_MANIFEST,KevConnector,KevNormalizer),
}
def runtime(root):
    root=Path(root);objects=FileObjectStore(root/"objects");meta=CanonicalMetadataStore.sqlite(root/"metadata.db",object_exists=objects.exists);catalog=SnapshotCatalogStore.sqlite(root/"catalog.db")
    return objects,meta,catalog,RevocationCoordinator(catalog,meta)
async def ingest(args):
    objects,meta,_catalog,rev=runtime(args.data_root);manifest,connector_cls,normalizer_cls=SOURCES[args.source]
    if args.source=="cve" and args.updated:connector=connector_cls((CVE_V5_UPDATED_FIXTURE,))
    elif args.source=="attack" and args.updated:connector=connector_cls(ATTACK_STIX_REVOKED_FIXTURE)
    else:connector=connector_cls()
    lifecycle=CyberSourceLifecycle(IngestionPipeline(manifest,connector,normalizer_cls(),objects,meta,rev))
    print(json.dumps(await lifecycle.ingest_all(),sort_keys=True))
def delete(args):
    objects,meta,_catalog,rev=runtime(args.data_root);manifest,connector_cls,normalizer_cls=SOURCES[args.source]
    lifecycle=CyberSourceLifecycle(IngestionPipeline(manifest,connector_cls(),normalizer_cls(),objects,meta,rev))
    print(json.dumps({"tombstoned":lifecycle.delete(args.identifier,args.reason)},sort_keys=True))
def rebuild(args):
    objects,meta,_catalog,_rev=runtime(args.data_root);bundle=CyberProjectionRebuilder(meta,objects).rebuild(system_manifest_id=args.manifest_id)
    print(json.dumps({"exact":len(bundle.exact),"lexical":len(bundle.lexical),"entities":len(bundle.entities),"assertions":len(bundle.assertions),"structured_rows":len(bundle.structured_rows)},sort_keys=True))
def coverage(_args):
    print(json.dumps([{"source_id":x.source_id,"status":x.status.value,"format":x.format,"reason":x.reason,"connector":x.connector,"normalizer":x.normalizer} for x in source_coverage_matrix()],sort_keys=True))
def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="cmd",required=True)
    q=sub.add_parser("coverage");q.set_defaults(fn=coverage)
    for name in ("ingest","delete"):
        q=sub.add_parser(name);q.add_argument("--data-root",required=True);q.add_argument("--source",choices=tuple(SOURCES),required=True)
        if name=="ingest":q.add_argument("--updated",action="store_true");q.set_defaults(fn=lambda a:asyncio.run(ingest(a)))
        else:q.add_argument("--identifier",required=True);q.add_argument("--reason",default="operator tombstone");q.set_defaults(fn=delete)
    q=sub.add_parser("rebuild");q.add_argument("--data-root",required=True);q.add_argument("--manifest-id",default="fixture");q.set_defaults(fn=rebuild)
    args=p.parse_args();args.fn(args)
if __name__=="__main__":main()
