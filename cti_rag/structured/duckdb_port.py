"""Resource-bounded DuckDB structured executor over server-registered preloaded datasets."""
from __future__ import annotations
import asyncio,json
from datetime import datetime,timezone
from cti_rag.contracts import ProvenanceRef,StructuredField,StructuredResult,TableKeyLocator,VerificationStatus,namespaced_uid,sha256_hex
from cti_rag.ports import BackendCapabilities,ChannelResult,ChannelStatus,StructuredRequest,TemporalMode
from .compiler import StructuredCompiler
from .models import StructuredQuerySpec,StructuredValidationError

class DuckDBStructuredPort:
    capabilities=BackendCapabilities(
        supported_filters=frozenset({"tenant","domain","access_label","source","temporal"}),
        temporal_modes=frozenset({TemporalMode.CURRENT,TemporalMode.HISTORICAL_PUBLIC,TemporalMode.HISTORICAL_SYSTEM_REPLAY}),
        snapshot_support=True,requires_snapshot=True,cancellation=True,max_batch_size=100000,
    )
    def __init__(self,registry,memory_limit="128MB",threads=1,max_scan_rows=100000,wall_time_seconds=2.0,template_resolver=None):
        self.registry=registry;self.compiler=StructuredCompiler(registry);self.memory_limit=memory_limit;self.threads=int(threads);self.max_scan_rows=int(max_scan_rows);self.wall_time_seconds=float(wall_time_seconds);self.template_resolver=template_resolver
        if self.threads<=0 or self.max_scan_rows<=0 or self.wall_time_seconds<=0:raise ValueError("invalid DuckDB worker bounds")
    def _connection(self):
        try:import duckdb
        except ImportError as exc:raise RuntimeError("duckdb dependency unavailable") from exc
        conn=duckdb.connect(database=":memory:",config={"enable_external_access":"false","allow_unsigned_extensions":"false"})
        conn.execute(f"SET memory_limit='{self.memory_limit}'");conn.execute(f"SET threads={self.threads}")
        for dataset_id in self.registry.names():
            registered=self.registry.get(dataset_id);schema=registered.schema
            columns=",".join(f'"{f.name}" {f.data_type}' for f in schema.fields);conn.execute(f'CREATE TABLE "{schema.table_name}" ({columns})')
            if registered.rows:
                names=tuple(f.name for f in schema.fields);marks=",".join("?" for _ in names)
                sql=f'INSERT INTO "{schema.table_name}" ('+','.join(f'"{n}"' for n in names)+f") VALUES ({marks})"
                conn.executemany(sql,[tuple(row.get(name) for name in names) for row in registered.rows])
                count=conn.execute(f'SELECT COUNT(*) FROM "{schema.table_name}"').fetchone()[0]
                if count>self.max_scan_rows:raise RuntimeError("dataset exceeds configured scan-row budget")
        return conn
    async def execute(self,request:StructuredRequest)->ChannelResult:
        if request.snapshot is None:return ChannelResult(ChannelStatus.REJECTED,reason="structured execution requires pinned snapshot")
        if not isinstance(request.spec,StructuredQuerySpec):return ChannelResult(ChannelStatus.REJECTED,reason="untyped structured query spec")
        try:compiled=self.compiler.compile(request.spec,request.scope,request.temporal,request.snapshot)
        except Exception as exc:return ChannelResult(ChannelStatus.REJECTED,reason=f"structured_validation:{type(exc).__name__}")
        async def run():
            conn=self._connection()
            try:
                rows=conn.execute(compiled.sql,compiled.params).fetchall();desc=conn.description
                lineage=tuple(r[0] for r in conn.execute(compiled.lineage_sql,compiled.lineage_params).fetchall())
            finally:conn.close()
            names=tuple(d[0] for d in desc);units=dict(compiled.result_units);fields=[]
            if len(rows)==1:
                for name,value in zip(names,rows[0]):fields.append(StructuredField(name,value,type(value).__name__,units.get(name)))
            else:
                for name in names:fields.append(StructuredField(name,tuple(row[names.index(name)] for row in rows),"column",units.get(name)))
            provenances=tuple(ProvenanceRef(uid,TableKeyLocator(request.spec.dataset_id,(("revision_uid",uid),))) for uid in lineage)
            schema=self.registry.get(request.spec.dataset_id).schema
            calc=sha256_hex({"query_spec":compiled.query_spec_hash,"dataset_snapshot":schema.data_snapshot,"revision_uids":lineage,"calculation_version":"duckdb-structured/1"})
            result_uid=namespaced_uid("structured","analytical.result",{"calc":calc,"spec":compiled.query_spec_hash})
            result=StructuredResult(
                result_uid,result_uid,lineage,tuple(fields),provenances,VerificationStatus.VERIFIED,calc,
                dataset_snapshot=schema.data_snapshot,query_spec_hash=compiled.query_spec_hash,null_rules=(schema.null_rule,),
                temporal_mode=request.temporal.mode.value,input_manifest=sha256_hex({"revision_uids":lineage}),calculation_version="duckdb-structured/1",
            )
            return ChannelResult(ChannelStatus.OK,(result,))
        timeout=self.wall_time_seconds
        if request.deadline is not None:timeout=min(timeout,max(0.0,(request.deadline-datetime.now(timezone.utc)).total_seconds()))
        if timeout<=0:return ChannelResult(ChannelStatus.TIMEOUT,reason="structured deadline exceeded")
        try:return await asyncio.wait_for(run(),timeout)
        except asyncio.TimeoutError:return ChannelResult(ChannelStatus.TIMEOUT,reason="structured execution timeout")
        except Exception as exc:return ChannelResult(ChannelStatus.UNAVAILABLE,reason=f"structured_execution:{type(exc).__name__}")
    async def run(self,node,scope,snapshot,prior,deadline,cancel_token):
        if self.template_resolver is None:return ChannelResult(ChannelStatus.UNSUPPORTED,reason="no structured template resolver installed")
        try:spec=self.template_resolver(node.query,node,scope,snapshot,prior)
        except Exception as exc:return ChannelResult(ChannelStatus.REJECTED,reason=f"structured_template:{type(exc).__name__}")
        return await self.execute(StructuredRequest(spec,scope,getattr(node,"temporal",None) or __import__("cti_rag.contracts",fromlist=["TemporalRequest"]).TemporalRequest(TemporalMode.CURRENT),snapshot,deadline,cancel_token))
