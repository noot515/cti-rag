#!/usr/bin/env python3
"""Read-only operational inspection. Prints counts/cursor/orphans; never environment secrets."""
import argparse,json
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--db",required=True); p.add_argument("--objects",required=True); p.add_argument("--source"); a=p.parse_args(argv)
    store=CanonicalMetadataStore.sqlite(a.db); objects=FileObjectStore(a.objects)
    out={"counts":store.counts(),"orphan_objects":len(objects.orphan_refs(store.referenced_object_digests()))}
    if a.source: out["checkpoint"]=store.checkpoint(a.source)
    print(json.dumps(out,indent=2,default=str,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
