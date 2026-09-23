from cti_rag.structured import DatasetRegistry,DatasetSchema,FieldSchema
COMMON=(
 FieldSchema("revision_uid","VARCHAR",nullable=False),FieldSchema("revision_order","BIGINT",nullable=False),FieldSchema("available_at","VARCHAR"),
 FieldSchema("valid_from","VARCHAR"),FieldSchema("valid_to","VARCHAR"),FieldSchema("system_manifest_id","VARCHAR",nullable=False),
 FieldSchema("dependency_available_at_max","VARCHAR"),FieldSchema("dependency_manifest_id","VARCHAR"),FieldSchema("tenant_id","VARCHAR",nullable=False),
 FieldSchema("domain","VARCHAR",nullable=False),FieldSchema("source_id","VARCHAR",nullable=False),FieldSchema("access_label","VARCHAR",nullable=False),
)
HUMANITIES_PASSAGE_SCHEMA=DatasetSchema("humanities_passages","humanities_passages",COMMON+(
 FieldSchema("work_id","VARCHAR",nullable=False),FieldSchema("edition_id","VARCHAR",nullable=False),FieldSchema("passage_id","VARCHAR",nullable=False),
 FieldSchema("role","VARCHAR",nullable=False),FieldSchema("language","VARCHAR",nullable=False),FieldSchema("rights","VARCHAR"),
 FieldSchema("transcription_quality","VARCHAR",nullable=False),FieldSchema("ocr_confidence","DOUBLE"),FieldSchema("date_start","VARCHAR"),FieldSchema("date_end_exclusive","VARCHAR"),
 FieldSchema("date_precision","VARCHAR",nullable=False),FieldSchema("date_label","VARCHAR"),FieldSchema("original_text","VARCHAR",nullable=False),FieldSchema("normalized_text","VARCHAR",nullable=False),
 FieldSchema("locator_json","VARCHAR",nullable=False),
),("edition_id","passage_id"),data_snapshot="humanities-fixture/1",allowed_join_keys=("work_id","edition_id","passage_id"))
def humanities_dataset_registry(rows):
    reg=DatasetRegistry();reg.register(HUMANITIES_PASSAGE_SCHEMA,tuple(row for ds,row in rows if ds=="humanities_passages"));return reg
def overlap_predicates(query_start:str,query_end_exclusive:str):
    from cti_rag.structured import Predicate,PredicateOperator
    if not query_start or not query_end_exclusive or query_end_exclusive<=query_start:raise ValueError("invalid historical overlap interval")
    return (Predicate("date_start",PredicateOperator.LT,query_end_exclusive),Predicate("date_end_exclusive",PredicateOperator.GT,query_start))
