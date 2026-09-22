from cti_rag.domains.spec import DomainSpec,IdentifierParser,RelationRule
SPEC=DomainSpec(
 name="cybersecurity",schemas=("cve/1","attack-technique/1","advisory/1"),
 identifiers=(IdentifierParser("cve",r"CVE-[0-9]{4}-[0-9]{4,}",True),IdentifierParser("cwe",r"CWE-[0-9]+",True),IdentifierParser("attack",r"T[0-9]{4}(?:\.[0-9]{3})?",True)),
 query_templates=(("identifier_lookup","exact canonical identifier lookup"),("advisory_search","lexical+dense public advisory search")),
 relation_rules=(RelationRule("has_weakness",("cve",),("cwe",)),RelationRule("maps_to_technique",("attack-flow",),("attack-technique",))),
 fixtures=({"id":"CVE-2026-0001","summary":"synthetic public vulnerability"},),
)
