from __future__ import annotations
import json
from datetime import datetime,timezone
from cti_rag.contracts import GraphPathHit,ScoreDirection,ScoreMetadata,TemporalMode,namespaced_uid,sha256_hex
from cti_rag.identifiers import default_identifier_registry
from cti_rag.ports import BackendCapabilities,ChannelResult,ChannelStatus,GraphRequest
from cti_rag.snapshots import ProjectionGeneration,ProjectionPayload
from .models import TraversalTemplate

def _iso(v): return None if v is None else v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
def _point(temporal):
    if temporal.mode==TemporalMode.HISTORICAL_PUBLIC:return datetime.fromisoformat(temporal.cutoff_iso.replace("Z","+00:00"))
    return datetime.now(timezone.utc) if temporal.mode==TemporalMode.CURRENT else None

class ReferenceGraphPort:
    kind="graph"
    capabilities=BackendCapabilities(supported_filters=frozenset({"tenant","domain","source","access_label","temporal","revocation"}),temporal_modes=frozenset(TemporalMode),snapshot_support=True,requires_snapshot=True,cancellation=True,max_batch_size=100,score_direction=ScoreDirection.UNORDERED)
    def __init__(self,catalog,evidence_store,templates,entity_resolution=None,identifier_registry=None):
        self.catalog=catalog; self.evidence_store=evidence_store; self.templates={t.template_id:t for t in templates}; self.resolution=entity_resolution; self.identifiers=identifier_registry or default_identifier_registry(); self.generations={}
    def build(self,request,entities,assertions):
        if request.kind!="graph": raise ValueError("graph builder received non-graph request")
        revisions=tuple(sorted(request.revision_uids)); allowed=set(revisions)
        entities=tuple(sorted(entities,key=lambda e:e.entity_uid)); assertions=tuple(sorted(assertions,key=lambda a:a.assertion_uid))
        for a in assertions:
            if a.revision_uid not in allowed: raise ValueError("graph assertion revision outside generation")
            if any(s.revision_uid not in allowed for s in a.support): raise ValueError("graph support revision outside generation")
            if not a.subject.entity_uid or not a.object.entity_uid: raise ValueError("graph assertions require typed canonical entity refs")
        identity={"entities":[(e.entity_uid,e.namespace,e.entity_type,e.identifier,e.label,e.source_id,_iso(e.available_at),_iso(e.valid_from),_iso(e.valid_to),e.system_manifest_id,e.policy.tenant_id,e.policy.access_label.value) for e in entities],"assertions":[(a.assertion_uid,a.revision_uid,a.subject.entity_uid,a.predicate,a.object.entity_uid,tuple((q.name,q.value) for q in a.qualifiers),tuple((s.revision_uid,repr(s.locator)) for s in a.support),a.epistemic.kind.value,a.source_id,_iso(a.available_at),_iso(a.valid_from),_iso(a.valid_to),a.system_manifest_id) for a in assertions]}
        checksum=sha256_hex(identity)
        existing=self.generations.get(request.generation_id)
        if existing and existing[0].checksum!=checksum: raise ValueError("immutable graph generation collision")
        payloads=tuple(ProjectionPayload(a.assertion_uid,a.revision_uid,json.dumps({"kind":"graph_assertion","assertion_uid":a.assertion_uid}),sha256_hex(a.assertion_uid.encode()),a.predicate) for a in assertions)
        generation=ProjectionGeneration(request.generation_id,"graph",revisions,tuple(request.representation_versions),checksum,True,True,True,request.quarantined_count,tuple(request.supported_query_capabilities),datetime.now(timezone.utc),payloads)
        self.generations[request.generation_id]=(generation,entities,assertions); return generation
    def validate(self,generation):
        current=self.generations.get(generation.generation_id); return bool(current and current[0].checksum==generation.checksum)
    def cleanup(self,generation_id): self.generations.pop(generation_id,None)
    def _policy(self,policy,source_id,scope,enforce_source=True):
        return policy is not None and policy.tenant_id in (scope.tenant_id,"public") and policy.access_label in scope.access_labels and policy.processing_class in scope.processing_classes and (not enforce_source or not scope.source_ids or source_id in scope.source_ids)
    def _time(self,obj,temporal):
        if temporal.mode==TemporalMode.HISTORICAL_SYSTEM_REPLAY:
            return getattr(obj,"system_manifest_id",None)==temporal.snapshot_manifest_id
        p=_point(temporal); available=getattr(obj,"available_at",None)
        if temporal.mode==TemporalMode.HISTORICAL_PUBLIC and available is None:return False
        if available is not None and available>p:return False
        vf=getattr(obj,"valid_from",None); vt=getattr(obj,"valid_to",None)
        return (vf is None or vf<=p) and (vt is None or vt>p)
    def _support_ok(self,a,revisions,scope,temporal):
        for ref in a.support:
            if ref.revision_uid not in revisions or self.catalog.is_revoked(ref.revision_uid): return False
            if self.evidence_store is None or self.evidence_store.resolve(ref) is None:return False
        return self._policy(a.policy,a.source_id or "",scope) and self._time(a,temporal)
    def _step_directions(self,template,a,subj,obj):
        out=[]
        for step in template.steps:
            if step.predicate!=a.predicate:continue
            if subj.entity_type in step.subject_types and obj.entity_type in step.object_types and step.direction in ("out","either"):out.append("out")
            if obj.entity_type in step.subject_types and subj.entity_type in step.object_types and step.direction in ("in","either"):out.append("in")
        return tuple(out)
    def _interval_compatible(self,assertions):
        starts=[a.valid_from for a in assertions if a.valid_from is not None]; ends=[a.valid_to for a in assertions if a.valid_to is not None]
        return not (starts and ends and max(starts)>=min(ends))
    async def traverse(self,request:GraphRequest):
        if request.snapshot is None:return ChannelResult(ChannelStatus.REJECTED,reason="graph traversal requires pinned snapshot")
        template=self.templates.get(request.template_id)
        if template is None:return ChannelResult(ChannelStatus.REJECTED,reason="unknown traversal template")
        if request.relations and any(r not in template.relations for r in request.relations):return ChannelResult(ChannelStatus.REJECTED,reason="relation outside traversal template")
        gid=self.catalog.generation_for_manifest(request.snapshot.manifest_id,"graph")
        if gid is None or gid not in self.generations:return ChannelResult(ChannelStatus.REJECTED,reason="snapshot has no graph generation")
        generation,entities,assertions=self.generations[gid]; revisions=set(generation.revision_uids)
        visible_entities={e.entity_uid:e for e in entities if self._policy(e.policy,e.source_id,request.scope,False) and not self.catalog.is_revoked(e.entity_uid)}
        visible_assertions=[]
        for a in assertions:
            if request.relations and a.predicate not in request.relations:continue
            if self.catalog.is_revoked(a.assertion_uid) or a.subject.entity_uid not in visible_entities or a.object.entity_uid not in visible_entities:continue
            if not self._support_ok(a,revisions,request.scope,request.temporal):continue
            directions=self._step_directions(template,a,visible_entities[a.subject.entity_uid],visible_entities[a.object.entity_uid])
            if not directions:continue
            visible_assertions.append((a,directions))
        seeds=[s for s in request.seeds if s in visible_entities]
        if not seeds:return ChannelResult(ChannelStatus.EMPTY,reason="no authorized graph seeds")
        adjacency={}
        for a,directions in visible_assertions:
            if "out" in directions:adjacency.setdefault(a.subject.entity_uid,[]).append((a,a.object.entity_uid,False))
            if "in" in directions:adjacency.setdefault(a.object.entity_uid,[]).append((a,a.subject.entity_uid,True))
        examined=0; truncated=False; outputs=[]
        frontier=[(s,(s,),()) for s in seeds]
        for depth in range(request.max_hops):
            nxt=[]
            for current,nodes,path_assertions in frontier:
                if request.cancellation_token is not None and request.cancellation_token.is_set():return ChannelResult(ChannelStatus.REJECTED,reason="request cancelled")
                if request.deadline is not None and datetime.now(timezone.utc)>=request.deadline:return ChannelResult(ChannelStatus.TIMEOUT,reason="graph deadline exceeded")
                edges=sorted(adjacency.get(current,()),key=lambda row:(row[0].assertion_uid,row[1]))
                if len(edges)>request.max_degree:truncated=True;edges=edges[:request.max_degree]
                for a,target,reversed_edge in edges:
                    if examined>=request.max_examined_edges:truncated=True;break
                    examined+=1
                    if target in nodes:continue
                    chain=path_assertions+(a,)
                    if not self._interval_compatible(chain):continue
                    new_nodes=nodes+(target,)
                    semantics="ontology_mapping_path" if template.mapping_semantics else "supported_relation_path"
                    provenances=tuple(p for x in chain for p in x.support); revs=tuple(dict.fromkeys(p.revision_uid for p in provenances))
                    labels=tuple(x.epistemic.kind.value for x in chain)
                    assertions_text=tuple(f"{x.subject.identifier} --{x.predicate}--> {x.object.identifier}" for x in chain)
                    path_uid=namespaced_uid("pth","graph.path",{"nodes":new_nodes,"assertions":tuple(x.assertion_uid for x in chain),"snapshot":request.snapshot.manifest_id})
                    outputs.append(GraphPathHit(path_uid,path_uid,revs,assertions_text,provenances,(ScoreMetadata("graph",None,ScoreDirection.UNORDERED,len(outputs)+1,"reference-graph"),),node_uids=new_nodes,assertion_uids=tuple(x.assertion_uid for x in chain),relation_types=tuple(x.predicate for x in chain),epistemic_labels=labels,semantics=semantics,truncated=False,
                        source_ids=tuple(sorted({x.source_id for x in chain if x.source_id})),
                        tenant_ids=tuple(sorted({x.policy.tenant_id for x in chain if x.policy is not None})),
                        access_labels=tuple(sorted({x.policy.access_label.value for x in chain if x.policy is not None})),
                        processing_classes=tuple(sorted({x.policy.processing_class.value for x in chain if x.policy is not None}))))
                    if len(outputs)>=request.max_paths:truncated=True;break
                    nxt.append((target,new_nodes,chain))
                if truncated and (examined>=request.max_examined_edges or len(outputs)>=request.max_paths):break
            if truncated and (examined>=request.max_examined_edges or len(outputs)>=request.max_paths):break
            frontier=nxt
            if not frontier:break
            if depth+1==request.max_hops and any(adjacency.get(n[0]) for n in frontier):truncated=True
        if not outputs:return ChannelResult(ChannelStatus.EMPTY,reason="no supported paths")
        if truncated: outputs=tuple(type(x)(**{**x.__dict__,"truncated":True}) for x in outputs)
        return ChannelResult(ChannelStatus.OK,tuple(outputs),truncated=truncated)
    async def run(self,node,scope,snapshot,temporal,prior,deadline,cancel_token):
        seeds=[]
        for token in node.query.replace("?"," ").replace(","," ").split():
            parsed=self.identifiers.parse_one(token.strip("()[]{}.;:"))
            if parsed and self.resolution is not None:
                hits=self.resolution.exact(parsed.namespace,parsed.object_type,parsed.canonical)
                seeds.extend(e.entity_uid for e in hits)
        if not seeds:return ChannelResult(ChannelStatus.EMPTY,reason="no resolvable graph seed")
        template_id="cyber-ontology-mapping" if "cyber-ontology-mapping" in self.templates else sorted(self.templates)[0]
        template=self.templates[template_id]
        return await self.traverse(GraphRequest(tuple(dict.fromkeys(seeds)),template.relations,scope,temporal,2,node.candidate_limit,snapshot,deadline,cancel_token,template_id))
