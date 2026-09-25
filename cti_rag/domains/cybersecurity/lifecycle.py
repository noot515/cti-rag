from __future__ import annotations
class CyberSourceLifecycle:
    def __init__(self,pipeline):self.pipeline=pipeline
    async def ingest_all(self):
        cursor=None;total={"accepted":0,"quarantined":0,"tombstoned":0,"pages":0}
        while True:
            result=await self.pipeline.ingest_page(cursor);total["pages"]+=1
            for key in ("accepted","quarantined","tombstoned"):total[key]+=int(result.get(key,0))
            if result["exhausted"]:break
            cursor=result["next_cursor"]
        return total
    def delete(self,stable_upstream_id,reason="operator tombstone"):
        count=0
        for revision_uid in self.pipeline.meta.revision_uids_for_source_object(self.pipeline.manifest.source_id,stable_upstream_id):
            if self.pipeline.revocations is not None:self.pipeline.revocations.admit(revision_uid,reason)
            else:self.pipeline.meta.add_revocation(revision_uid,reason)
            count+=1
        return count
