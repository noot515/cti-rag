from cti_rag.structured import DatasetRegistry,DatasetSchema,FieldSchema
COMMON=(
 FieldSchema("revision_uid","VARCHAR",nullable=False),FieldSchema("revision_order","BIGINT",nullable=False),FieldSchema("available_at","VARCHAR"),
 FieldSchema("valid_from","VARCHAR"),FieldSchema("valid_to","VARCHAR"),FieldSchema("system_manifest_id","VARCHAR",nullable=False),
 FieldSchema("dependency_available_at_max","VARCHAR"),FieldSchema("dependency_manifest_id","VARCHAR"),FieldSchema("tenant_id","VARCHAR",nullable=False),
 FieldSchema("domain","VARCHAR",nullable=False),FieldSchema("source_id","VARCHAR",nullable=False),FieldSchema("access_label","VARCHAR",nullable=False),
)
FUNDAMENTAL_SCHEMA=DatasetSchema("quant_fundamental","quant_fundamental",COMMON+(
 FieldSchema("cik","VARCHAR",nullable=False),FieldSchema("accession","VARCHAR",nullable=False),FieldSchema("form","VARCHAR"),FieldSchema("tag","VARCHAR",nullable=False),FieldSchema("namespace","VARCHAR",nullable=False),
 FieldSchema("value","DOUBLE"),FieldSchema("unit","VARCHAR",nullable=False),FieldSchema("currency","VARCHAR"),FieldSchema("period_start","VARCHAR"),FieldSchema("period_end","VARCHAR"),FieldSchema("reporting_basis","VARCHAR"),FieldSchema("context_id","VARCHAR"),FieldSchema("source_coordinate","VARCHAR",nullable=False),FieldSchema("amendment","BOOLEAN",nullable=False),
),("cik","tag","period_end","unit","context_id"),data_snapshot="quant-fixture/1",allowed_join_keys=("cik","accession"))
MACRO_SCHEMA=DatasetSchema("quant_macro","quant_macro",COMMON+(
 FieldSchema("series_id","VARCHAR",nullable=False),FieldSchema("observation_date","VARCHAR",nullable=False),FieldSchema("value","DOUBLE"),FieldSchema("unit","VARCHAR",nullable=False),FieldSchema("realtime_start","VARCHAR",nullable=False),FieldSchema("realtime_end","VARCHAR"),FieldSchema("frequency","VARCHAR"),FieldSchema("seasonal_adjustment","VARCHAR"),FieldSchema("source_coordinate","VARCHAR",nullable=False),
),("series_id","observation_date"),data_snapshot="quant-fixture/1",allowed_join_keys=("series_id",))
PRICE_SCHEMA=DatasetSchema("quant_prices","quant_prices",COMMON+(
 FieldSchema("security_id","VARCHAR",nullable=False),FieldSchema("ticker","VARCHAR",nullable=False),FieldSchema("exchange","VARCHAR",nullable=False),FieldSchema("trading_date","VARCHAR",nullable=False),FieldSchema("close","DOUBLE","currency"),FieldSchema("currency","VARCHAR",nullable=False),FieldSchema("calendar","VARCHAR",nullable=False),FieldSchema("timezone","VARCHAR",nullable=False),FieldSchema("adjusted","BOOLEAN",nullable=False),FieldSchema("provider","VARCHAR",nullable=False),FieldSchema("corporate_action_version","VARCHAR"),FieldSchema("source_coordinate","VARCHAR",nullable=False),
),("security_id","trading_date","provider"),data_snapshot="quant-fixture/1",allowed_join_keys=("security_id",))
ACTION_SCHEMA=DatasetSchema("quant_corporate_actions","quant_corporate_actions",COMMON+(
 FieldSchema("security_id","VARCHAR",nullable=False),FieldSchema("action_type","VARCHAR",nullable=False),FieldSchema("effective_date","VARCHAR",nullable=False),FieldSchema("ratio","DOUBLE","ratio"),FieldSchema("currency","VARCHAR"),FieldSchema("provider","VARCHAR",nullable=False),FieldSchema("source_coordinate","VARCHAR",nullable=False),
),("security_id","action_type","effective_date","provider"),data_snapshot="quant-fixture/1",allowed_join_keys=("security_id",))
ALIAS_SCHEMA=DatasetSchema("quant_security_alias","quant_security_alias",COMMON+(
 FieldSchema("security_id","VARCHAR",nullable=False),FieldSchema("issuer_cik","VARCHAR",nullable=False),FieldSchema("ticker","VARCHAR",nullable=False),FieldSchema("exchange","VARCHAR",nullable=False),FieldSchema("alias_from","VARCHAR",nullable=False),FieldSchema("alias_to","VARCHAR"),FieldSchema("listed_from","VARCHAR"),FieldSchema("listed_to","VARCHAR"),FieldSchema("delisted_at","VARCHAR"),
),("ticker","exchange","alias_from"),data_snapshot="quant-fixture/1",allowed_join_keys=("security_id","issuer_cik"))
UNIVERSE_SCHEMA=DatasetSchema("quant_universe","quant_universe",COMMON+(
 FieldSchema("universe_id","VARCHAR",nullable=False),FieldSchema("security_id","VARCHAR",nullable=False),FieldSchema("member_from","VARCHAR",nullable=False),FieldSchema("member_to","VARCHAR"),FieldSchema("delisted_at","VARCHAR"),
),("universe_id","security_id","member_from"),data_snapshot="quant-fixture/1",allowed_join_keys=("security_id",))
def quant_dataset_registry(rows):
    grouped={k:[] for k in ("quant_fundamental","quant_macro","quant_prices","quant_corporate_actions","quant_security_alias","quant_universe")}
    for ds,row in rows:grouped[ds].append(row)
    reg=DatasetRegistry()
    for schema in (FUNDAMENTAL_SCHEMA,MACRO_SCHEMA,PRICE_SCHEMA,ACTION_SCHEMA,ALIAS_SCHEMA,UNIVERSE_SCHEMA):reg.register(schema,tuple(grouped[schema.dataset_id]))
    return reg
