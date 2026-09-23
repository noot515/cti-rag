"""Small public deterministic analytical fixtures for temporal/numeric contract tests."""
from __future__ import annotations
from ipaddress import ip_network
from .models import DatasetSchema,FieldSchema
from .registry import DatasetRegistry

COMMON=(
    FieldSchema("revision_uid","VARCHAR",nullable=False),FieldSchema("revision_order","INTEGER",nullable=False),
    FieldSchema("available_at","VARCHAR"),FieldSchema("valid_from","VARCHAR"),FieldSchema("valid_to","VARCHAR"),
    FieldSchema("system_manifest_id","VARCHAR",nullable=False),FieldSchema("dependency_available_at_max","VARCHAR"),FieldSchema("dependency_manifest_id","VARCHAR"),
    FieldSchema("tenant_id","VARCHAR",nullable=False),FieldSchema("domain","VARCHAR",nullable=False),FieldSchema("source_id","VARCHAR",nullable=False),FieldSchema("access_label","VARCHAR",nullable=False),
)

def _prefix_bounds(value):
    net=ip_network(value);return int(net.network_address),int(net.broadcast_address)

def fixture_registry():
    reg=DatasetRegistry()
    macro=DatasetSchema("macro","macro_fixture",COMMON+(
        FieldSchema("series_id","VARCHAR",nullable=False),FieldSchema("observation_date","VARCHAR",nullable=False),FieldSchema("value","DOUBLE","index"),
    ),("series_id","observation_date"),data_snapshot="macro-fixture/1",allowed_join_keys=("series_id",))
    reg.register(macro,(
        {"revision_uid":"macro-r1","revision_order":1,"available_at":"2025-01-02T00:00:00Z","valid_from":"2024-12-01T00:00:00Z","valid_to":None,"system_manifest_id":"manifest-early","dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"quant","source_id":"macro","access_label":"public","series_id":"GDPX","observation_date":"2024-12-01","value":100.0},
        {"revision_uid":"macro-r2","revision_order":2,"available_at":"2026-02-01T00:00:00Z","valid_from":"2024-12-01T00:00:00Z","valid_to":None,"system_manifest_id":"manifest-late","dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"quant","source_id":"macro","access_label":"public","series_id":"GDPX","observation_date":"2024-12-01","value":110.0},
        {"revision_uid":"macro-late-ingest","revision_order":1,"available_at":"2025-01-15T00:00:00Z","valid_from":"2024-11-01T00:00:00Z","valid_to":None,"system_manifest_id":"manifest-late","dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"quant","source_id":"macro","access_label":"public","series_id":"LATE","observation_date":"2024-11-01","value":5.0},
        {"revision_uid":"macro-unknown","revision_order":1,"available_at":None,"valid_from":"2024-10-01T00:00:00Z","valid_to":None,"system_manifest_id":"manifest-late","dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"quant","source_id":"macro","access_label":"public","series_id":"UNKNOWN","observation_date":"2024-10-01","value":7.0},
        {"revision_uid":"macro-null","revision_order":1,"available_at":"2025-01-01T00:00:00Z","valid_from":"2024-09-01T00:00:00Z","valid_to":None,"system_manifest_id":"manifest-early","dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"quant","source_id":"macro","access_label":"public","series_id":"NULLABLE","observation_date":"2024-09-01","value":None},
    ))
    vuln=DatasetSchema("vulnerability","vuln_fixture",COMMON+(
        FieldSchema("cve_id","VARCHAR",nullable=False),FieldSchema("cvss","DOUBLE","score"),FieldSchema("exploited","BOOLEAN"),
    ),("cve_id",),data_snapshot="vuln-fixture/1",allowed_join_keys=("cve_id",))
    reg.register(vuln,tuple(
        {"revision_uid":f"vuln-r{i}","revision_order":1,"available_at":"2026-01-01T00:00:00Z","valid_from":None,"valid_to":None,"system_manifest_id":"manifest-late","dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"cybersecurity","source_id":"vuln","access_label":"public","cve_id":f"CVE-2026-{i:04d}","cvss":float(i%11),"exploited":bool(i%2)} for i in range(1,121)
    ))
    nets=DatasetSchema("prefixes","prefix_fixture",COMMON+(
        FieldSchema("prefix","VARCHAR",nullable=False),FieldSchema("prefix_start","UBIGINT",nullable=False),FieldSchema("prefix_end","UBIGINT",nullable=False),FieldSchema("owner","VARCHAR"),
    ),("prefix",),data_snapshot="prefix-fixture/1")
    rows=[]
    for i,prefix in enumerate(("192.0.2.0/24","198.51.100.0/24"),1):
        start,end=_prefix_bounds(prefix);rows.append({"revision_uid":f"net-r{i}","revision_order":1,"available_at":"2026-01-01T00:00:00Z","valid_from":None,"valid_to":None,"system_manifest_id":"manifest-late","dependency_available_at_max":None,"dependency_manifest_id":None,"tenant_id":"public","domain":"networking","source_id":"prefixes","access_label":"public","prefix":prefix,"prefix_start":start,"prefix_end":end,"owner":f"owner-{i}"})
    reg.register(nets,tuple(rows))
    return reg
