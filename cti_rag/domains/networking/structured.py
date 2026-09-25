from cti_rag.structured import DatasetRegistry,DatasetSchema,FieldSchema
COMMON=(
 FieldSchema("revision_uid","VARCHAR",nullable=False),FieldSchema("revision_order","BIGINT",nullable=False),FieldSchema("available_at","VARCHAR"),
 FieldSchema("valid_from","VARCHAR"),FieldSchema("valid_to","VARCHAR"),FieldSchema("system_manifest_id","VARCHAR",nullable=False),
 FieldSchema("dependency_available_at_max","VARCHAR"),FieldSchema("dependency_manifest_id","VARCHAR"),FieldSchema("tenant_id","VARCHAR",nullable=False),
 FieldSchema("domain","VARCHAR",nullable=False),FieldSchema("source_id","VARCHAR",nullable=False),FieldSchema("access_label","VARCHAR",nullable=False),
)
PREFIX_FIELDS=(FieldSchema("prefix","VARCHAR",nullable=False),FieldSchema("prefix_start","VARCHAR",nullable=False),FieldSchema("prefix_end","VARCHAR",nullable=False),FieldSchema("prefix_family","INTEGER",nullable=False),FieldSchema("prefix_length","INTEGER",nullable=False))
BGP_SCHEMA=DatasetSchema("network_bgp","network_bgp",COMMON+PREFIX_FIELDS+(
 FieldSchema("collector","VARCHAR",nullable=False),FieldSchema("vantage_point","VARCHAR",nullable=False),FieldSchema("peer_asn","VARCHAR",nullable=False),FieldSchema("origin_asn","VARCHAR",nullable=False),
 FieldSchema("observation_start","VARCHAR",nullable=False),FieldSchema("observation_end","VARCHAR"),FieldSchema("as_path","VARCHAR"),
),("collector","prefix","observation_start","peer_asn"),data_snapshot="network-fixture/1",allowed_join_keys=("prefix","origin_asn"))
RPKI_SCHEMA=DatasetSchema("network_rpki","network_rpki",COMMON+PREFIX_FIELDS+(
 FieldSchema("max_length","INTEGER",nullable=False),FieldSchema("asn","VARCHAR",nullable=False),
),("prefix","max_length","asn"),data_snapshot="network-fixture/1",allowed_join_keys=("prefix","asn"))
DNS_SCHEMA=DatasetSchema("network_dns","network_dns",COMMON+(
 FieldSchema("qname","VARCHAR",nullable=False),FieldSchema("rrtype","VARCHAR",nullable=False),FieldSchema("rdata","VARCHAR",nullable=False),FieldSchema("ttl_seconds","INTEGER","seconds"),
 FieldSchema("resolver","VARCHAR",nullable=False),FieldSchema("vantage_point","VARCHAR",nullable=False),FieldSchema("observed_at","VARCHAR",nullable=False),
),("qname","rrtype","resolver","observed_at","rdata"),data_snapshot="network-fixture/1")
RDAP_SCHEMA=DatasetSchema("network_rdap","network_rdap",COMMON+PREFIX_FIELDS+(
 FieldSchema("entity_handle","VARCHAR",nullable=False),FieldSchema("entity_name","VARCHAR"),FieldSchema("registration_start","VARCHAR"),FieldSchema("registration_end","VARCHAR"),
),("prefix","entity_handle"),data_snapshot="network-fixture/1",allowed_join_keys=("prefix",))
def networking_dataset_registry(rows):
    grouped={k:[] for k in ("network_bgp","network_rpki","network_dns","network_rdap")}
    for dataset,row in rows:grouped[dataset].append(row)
    reg=DatasetRegistry()
    reg.register(BGP_SCHEMA,tuple(grouped["network_bgp"]));reg.register(RPKI_SCHEMA,tuple(grouped["network_rpki"]));reg.register(DNS_SCHEMA,tuple(grouped["network_dns"]));reg.register(RDAP_SCHEMA,tuple(grouped["network_rdap"]))
    return reg
