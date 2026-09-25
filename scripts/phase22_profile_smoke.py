#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,tempfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.operations import CacheBundle,OperationalPaths,load_profile,scheduler_from_profile
from cti_rag.snapshots import SnapshotCatalogStore

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--profile",required=True);p.add_argument("--root");args=p.parse_args(argv)
    profile=load_profile(args.profile)
    owned=None
    if args.root is None:
        owned=tempfile.TemporaryDirectory();root=Path(owned.name)
    else:root=Path(args.root)
    paths=OperationalPaths.from_root(root);objects=FileObjectStore(paths.objects)
    meta=CanonicalMetadataStore.sqlite(paths.canonical_db,object_exists=objects.exists);catalog=SnapshotCatalogStore.sqlite(paths.catalog_db);caches=CacheBundle(paths.cache_root)
    scheduler=scheduler_from_profile(profile)
    report={"profile":profile.name,"root":str(paths.root),"components":profile.components,"exposed_ports":profile.exposed_ports,"egress_policy":profile.egress_policy,"canonical_counts":meta.counts(),"current_manifest_id":None if catalog.current_manifest() is None else catalog.current_manifest().manifest_id,"cache_files":sorted(p.name for p in paths.cache_root.glob("*.sqlite")),"scheduler_sizes":scheduler.sizes(),"scheduler_limits":dict(profile.scheduler_limits)}
    print(json.dumps(report,sort_keys=True))
    if owned is not None:owned.cleanup()
    return 0
if __name__=="__main__":raise SystemExit(main())
