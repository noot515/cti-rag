from cti_rag.domains.spec import DomainSpec,IdentifierParser,RelationRule
SPEC=DomainSpec(
 name="quant",
 schemas=("sec-company/1","sec-filing-xbrl/1","fred-alfred-observation/1","market-price/1","corporate-action/1","security-master/1"),
 identifiers=(IdentifierParser("cik",r"[0-9]{10}"),IdentifierParser("sec-accession",r"[0-9]{10}-[0-9]{2}-[0-9]{6}")),
 query_templates=(
   ("company_lookup","exact CIK lookup"),
   ("filing_lookup","exact SEC accession lookup"),
   ("filing_explanation","lexical+dense cited filing-section retrieval"),
   ("point_in_time_metric","verified structured point-in-time value/filter"),
   ("returns","verified structured return calculation"),
   ("event_study","verified event-study calculation with pinned benchmark/windows"),
 ),
 relation_rules=(RelationRule("filed_by",("sec-filing",),("legal-entity",)),RelationRule("amends",("sec-filing",),("sec-filing",)),RelationRule("issued_by",("security",),("legal-entity",))),
 fixtures=({"cik":"0000123456","form":"8-K"},{"ticker":"XYZ","exchange":"XNAS","requires_time":True}),
)
