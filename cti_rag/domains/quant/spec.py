from cti_rag.domains.spec import DomainSpec,IdentifierParser,RelationRule
SPEC=DomainSpec(
 name="quant",schemas=("sec-filing/1","macro-series/1","market-observation/1"),
 identifiers=(IdentifierParser("cik",r"[0-9]{10}"),IdentifierParser("ticker",r"[A-Z][A-Z0-9.\-]{0,9}",True)),
 query_templates=(("filing_lookup","exact CIK/accession lookup"),("point_in_time_metric","verified structured calculation")),
 relation_rules=(RelationRule("issued_by",("security",),("legal-entity",)),),fixtures=({"cik":"0000320193","form":"10-K"},),
)
