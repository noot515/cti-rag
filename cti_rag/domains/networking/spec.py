from cti_rag.domains.spec import DomainSpec,IdentifierParser,RelationRule
SPEC=DomainSpec(
 name="networking",schemas=("rfc/1","route-observation/1"),
 identifiers=(IdentifierParser("asn",r"AS[0-9]+",True),IdentifierParser("rfc",r"RFC[ -]?[0-9]+",True)),
 query_templates=(("rfc_lookup","resolve RFC identifier"),("route_observation","structured point-in-time route query")),
 relation_rules=(RelationRule("announced_by",("prefix",),("asn",)),RelationRule("updates",("rfc",),("rfc",))),
 fixtures=({"id":"RFC 4271","title":"BGP-4"},),
)
