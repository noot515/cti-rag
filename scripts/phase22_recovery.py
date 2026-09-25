#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.operations import OperationalPaths,RecoveryManager
from cti_rag.snapshots import SnapshotCatalogStore,SnapshotPublisher

def manager(root):
    paths=OperationalPaths.from_root(root);objects=FileObjectStore(paths.objects);meta=CanonicalMetadataStore.sqlite(paths.canonical_db,object_exists=objects.exists);catalog=SnapshotCatalogStore.sqlite(paths.catalog_db);publisher=SnapshotPublisher(catalog)
    return RecoveryManager(objects,meta,catalog,publisher)

def main(argv=None):
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="cmd",required=True)
    for name in ("backup","restore"):
        q=sub.add_parser(name);q.add_argument("--root",required=True);q.add_argument("--backup",required=True)
    q=sub.add_parser("health");q.add_argument("--root",required=True)
    q=sub.add_parser("rollback");q.add_argument("--root",required=True);q.add_argument("--manifest",required=True)
    q=sub.add_parser("rebuild-fixture-index");q.add_argument("--root",required=True);q.add_argument("--output",required=True)
    args=p.parse_args(argv);m=manager(args.root)
    if args.cmd=="backup":result=m.create_backup(args.backup)
    elif args.cmd=="restore":result=m.restore_backup(args.backup)
    elif args.cmd=="health":result=m.health()
    elif args.cmd=="rollback":result={"manifest_id":m.rollback(args.manifest).manifest_id}
    else:result=m.rebuild_fixture_index(args.output)
    print(json.dumps(result,sort_keys=True,default=str));return 0
if __name__=="__main__":raise SystemExit(main())
