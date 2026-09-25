from cti_rag.domains.spec import DomainSpec,IdentifierParser,RelationRule
SPEC=DomainSpec(
 name="privacy",schemas=("privacy-guidance/1","tracker/1","private-exposure/1"),
 identifiers=(IdentifierParser("domain",r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),),
 query_templates=(("public_guidance","public privacy guidance search"),("tracker_lookup","exact tracker/domain lookup")),
 relation_rules=(RelationRule("operated_by",("tracker",),("organization",)),),fixtures=({"domain":"tracker.example","classification":"synthetic"},),
)
