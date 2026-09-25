from cti_rag.structured import DatasetRegistry,DatasetSchema,FieldSchema
COMMON=(
 FieldSchema("revision_uid","VARCHAR",nullable=False),FieldSchema("revision_order","BIGINT",nullable=False),FieldSchema("available_at","VARCHAR"),
 FieldSchema("valid_from","VARCHAR"),FieldSchema("valid_to","VARCHAR"),FieldSchema("system_manifest_id","VARCHAR",nullable=False),
 FieldSchema("dependency_available_at_max","VARCHAR"),FieldSchema("dependency_manifest_id","VARCHAR"),FieldSchema("tenant_id","VARCHAR",nullable=False),
 FieldSchema("domain","VARCHAR",nullable=False),FieldSchema("source_id","VARCHAR",nullable=False),FieldSchema("access_label","VARCHAR",nullable=False),
)
CVSS_SCHEMA=DatasetSchema("cyber_cvss","cyber_cvss",COMMON+(
 FieldSchema("cve_id","VARCHAR",nullable=False),FieldSchema("cvss_scheme","VARCHAR",nullable=False),FieldSchema("cvss_score","DOUBLE","score"),
 FieldSchema("cvss_severity","VARCHAR"),FieldSchema("vector","VARCHAR"),FieldSchema("source_container","VARCHAR"),
),("cve_id","source_id","cvss_scheme","source_container"),data_snapshot="cyber-source-fixture/1",allowed_join_keys=("cve_id",))
KEV_SCHEMA=DatasetSchema("cyber_kev","cyber_kev",COMMON+(
 FieldSchema("cve_id","VARCHAR",nullable=False),FieldSchema("kev","BOOLEAN",nullable=False),FieldSchema("date_added","VARCHAR"),FieldSchema("due_date","VARCHAR"),FieldSchema("known_ransomware_campaign_use","VARCHAR"),
),("cve_id","source_id"),data_snapshot="cyber-source-fixture/1",allowed_join_keys=("cve_id",))
def cyber_dataset_registry(structured_rows):
    reg=DatasetRegistry();grouped={"cyber_cvss":[],"cyber_kev":[]}
    for dataset,row in structured_rows:grouped.setdefault(dataset,[]).append(row)
    reg.register(CVSS_SCHEMA,tuple(grouped["cyber_cvss"]));reg.register(KEV_SCHEMA,tuple(grouped["cyber_kev"]));return reg
