"""Safe structured-query compiler: schema identifiers only, parameterized values only."""
from __future__ import annotations
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Tuple
from cti_rag.contracts import TemporalMode
from .models import AggregationFunction,PredicateOperator,StructuredQuerySpec,StructuredValidationError,UnknownAvailabilityPolicy

@dataclass(frozen=True)
class CompiledStructuredQuery:
    sql:str
    params:Tuple[object,...]
    lineage_sql:str
    lineage_params:Tuple[object,...]
    query_spec_hash:str
    result_units:Tuple[Tuple[str,str|None],...]

def _q(name):return '"' + name.replace('"','""') + '"'

class StructuredCompiler:
    ALLOWED_ORDER=("asc","desc")
    def __init__(self,registry):self.registry=registry
    def compile(self,spec:StructuredQuerySpec,scope,temporal,snapshot):
        base=self.registry.get(spec.dataset_id); schemas={spec.dataset_id:base.schema}
        for join in spec.joins:schemas[join.dataset_id]=self.registry.get(join.dataset_id).schema
        aliases={spec.dataset_id:"d0"}; join_sql=[]; params=[]
        for i,join in enumerate(spec.joins,1):
            left=base.schema.field(join.left_field); right=schemas[join.dataset_id].field(join.right_field)
            if join.left_field not in base.schema.allowed_join_keys or join.right_field not in schemas[join.dataset_id].allowed_join_keys:raise StructuredValidationError("join key is not allowlisted")
            if left.data_type!=right.data_type:raise StructuredValidationError("ambiguous/incompatible join types")
            alias=f"d{i}";aliases[join.dataset_id]=alias
            join_sql.append(f'JOIN {_q(schemas[join.dataset_id].table_name)} {alias} ON d0.{_q(join.left_field)}={alias}.{_q(join.right_field)}')
        clauses=[]; tparams=[]
        # Authorization is expressed inside the analytical query, never after presentation limiting.
        if "tenant_id" in {f.name for f in base.schema.fields}:
            clauses.append('(d0."tenant_id"=? OR d0."tenant_id"=?)');tparams.extend((scope.tenant_id,"public"))
        if "domain" in {f.name for f in base.schema.fields}:
            clauses.append('d0."domain" IN ('+','.join("?" for _ in scope.domains)+')');tparams.extend(scope.domains)
        if "access_label" in {f.name for f in base.schema.fields}:
            labels=tuple(v.value for v in scope.access_labels);clauses.append('d0."access_label" IN ('+','.join("?" for _ in labels)+')');tparams.extend(labels)
        if scope.source_ids and "source_id" in {f.name for f in base.schema.fields}:
            clauses.append('d0."source_id" IN ('+','.join("?" for _ in scope.source_ids)+')');tparams.extend(scope.source_ids)
        af=base.schema.availability_field
        if temporal.mode==TemporalMode.HISTORICAL_PUBLIC:
            if not temporal.cutoff_iso:raise StructuredValidationError("historical public query requires cutoff")
            if spec.unknown_availability_policy==UnknownAvailabilityPolicy.REJECT:
                clauses.append(f'd0.{_q(af)} IS NOT NULL')
            else:clauses.append(f'd0.{_q(af)} IS NOT NULL')
            clauses.append(f'd0.{_q(af)}<=?');tparams.append(temporal.cutoff_iso)
            dep=base.schema.dependency_available_field
            if dep in {f.name for f in base.schema.fields}:
                clauses.append(f'(d0.{_q(dep)} IS NULL OR d0.{_q(dep)}<=?)');tparams.append(temporal.cutoff_iso)
        elif temporal.mode==TemporalMode.HISTORICAL_SYSTEM_REPLAY:
            manifest=temporal.snapshot_manifest_id or getattr(snapshot,"manifest_id",None)
            if not manifest:raise StructuredValidationError("system replay requires manifest")
            clauses.append(f'd0.{_q(base.schema.system_manifest_field)}=?');tparams.append(manifest)
            depm=base.schema.dependency_manifest_field
            if depm in {f.name for f in base.schema.fields}:
                clauses.append(f'(d0.{_q(depm)} IS NULL OR d0.{_q(depm)}=?)');tparams.append(manifest)
        if spec.valid_at_iso:
            clauses.append(f'(d0.{_q(base.schema.valid_from_field)} IS NULL OR d0.{_q(base.schema.valid_from_field)}<=?)');tparams.append(spec.valid_at_iso)
            clauses.append(f'(d0.{_q(base.schema.valid_to_field)} IS NULL OR d0.{_q(base.schema.valid_to_field)}>?)');tparams.append(spec.valid_at_iso)
        for pred in spec.predicates:
            field=base.schema.field(pred.field);col=f'd0.{_q(field.name)}'
            if pred.operator==PredicateOperator.IP_IN_PREFIX:
                # Schema controls the paired range/family fields; the client supplies only the point IP.
                start=base.schema.field(pred.field+"_start");end=base.schema.field(pred.field+"_end")
                try:address=ip_address(str(pred.value))
                except ValueError as exc:raise StructuredValidationError("invalid IP address") from exc
                textual=start.data_type.upper() in ("VARCHAR","TEXT","CHAR")
                value=address.packed.hex().rjust(32,"0") if textual else int(address)
                clauses.append(f'd0.{_q(start.name)}<=? AND d0.{_q(end.name)}>=?');tparams.extend((value,value))
                family_name=pred.field+"_family"
                if family_name in {f.name for f in base.schema.fields}:
                    clauses.append(f'd0.{_q(family_name)}=?');tparams.append(address.version)
                continue
            if pred.operator in (PredicateOperator.IS_NULL,PredicateOperator.NOT_NULL):
                clauses.append(f"{col} IS {'NOT ' if pred.operator==PredicateOperator.NOT_NULL else ''}NULL");continue
            if pred.operator==PredicateOperator.IN:
                values=tuple(pred.value or ())
                if not values:raise StructuredValidationError("IN predicate requires values")
                clauses.append(f"{col} IN ("+','.join("?" for _ in values)+")");tparams.extend(values);continue
            if pred.operator==PredicateOperator.BETWEEN:
                clauses.append(f"{col} BETWEEN ? AND ?");tparams.extend((pred.value,pred.second_value));continue
            op={PredicateOperator.EQ:"=",PredicateOperator.NE:"!=",PredicateOperator.LT:"<",PredicateOperator.LE:"<=",PredicateOperator.GT:">",PredicateOperator.GE:">="}[pred.operator]
            clauses.append(f"{col}{op}?");tparams.append(pred.value)
        where=" AND ".join(clauses) if clauses else "TRUE"
        keys=','.join(f'd0.{_q(k)}' for k in base.schema.logical_key_fields)
        revision_order=f'd0.{_q(base.schema.revision_order_field)}'
        joined=f'{_q(base.schema.table_name)} d0 '+" ".join(join_sql)
        eligible=f"SELECT *, ROW_NUMBER() OVER (PARTITION BY {keys} ORDER BY {revision_order} DESC, d0.{_q(base.schema.revision_uid_field)} DESC) AS __revision_rank FROM {joined} WHERE {where}"
        selected="SELECT * FROM ("+eligible+") __eligible WHERE __revision_rank=1"
        select=[];units=[]
        for field_name in spec.select_fields:
            field=base.schema.field(field_name);select.append(_q(field_name));units.append((field_name,field.unit))
        for agg in spec.aggregations:
            if agg.function==AggregationFunction.COUNT:expr="COUNT(*)"
            else:
                field=base.schema.field(agg.field);expr=f"{agg.function.value.upper()}({_q(field.name)})"
            select.append(f"{expr} AS {_q(agg.alias)}")
            unit=agg.unit
            if unit is None and agg.function!=AggregationFunction.COUNT:unit=base.schema.field(agg.field).unit
            if unit is None and agg.function==AggregationFunction.COUNT:unit="count"
            units.append((agg.alias,unit))
        if not select:raise StructuredValidationError("query must select fields or aggregations")
        group=""
        if spec.group_by:
            for name in spec.group_by:base.schema.field(name)
            group=" GROUP BY "+','.join(_q(v) for v in spec.group_by)
        order=""
        if spec.order_by:
            chunks=[]
            allowed={name for name,_ in units}|set(spec.select_fields)
            for name,direction in spec.order_by:
                if name not in allowed or direction.lower() not in self.ALLOWED_ORDER:raise StructuredValidationError("invalid order by")
                chunks.append(f'{_q(name)} {direction.upper()}')
            order=" ORDER BY "+','.join(chunks)
        sql=f"WITH selected AS ({selected}) SELECT "+','.join(select)+" FROM selected"+group+order+" LIMIT ?"
        params=tuple(tparams)+(spec.presentation_limit,)
        lineage_sql=f"WITH selected AS ({selected}) SELECT {_q(base.schema.revision_uid_field)} FROM selected ORDER BY {_q(base.schema.revision_uid_field)}"
        return CompiledStructuredQuery(sql,params,lineage_sql,tuple(tparams),spec.query_spec_hash,tuple(units))
