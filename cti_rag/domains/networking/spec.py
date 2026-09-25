from cti_rag.domains.spec import DomainSpec,IdentifierParser,RelationRule
SPEC=DomainSpec(
 name="networking",
 schemas=("rfc-document/1","bgp-observation/1","rpki-authorization/1","dns-observation/1","rdap-registration/1"),
 identifiers=(
   IdentifierParser("asn",r"AS[0-9]+",True),
   IdentifierParser("rfc",r"RFC[ -]?[0-9]+",True),
   IdentifierParser("cidr",r"(?:[0-9A-Fa-f:.]+)/[0-9]{1,3}"),
 ),
 query_templates=(
   ("rfc_lookup","exact RFC identifier lookup"),
   ("rfc_explanation","lexical+dense RFC section retrieval"),
   ("route_observation","structured point-in-time prefix/ASN observation query"),
   ("prefix_longest_match","structured IP containment ordered by longest prefix"),
   ("network_relation","source-backed graph relation for announcement, registration, or RPKI authorization"),
 ),
 relation_rules=(
   RelationRule("announced_by",("prefix",),("asn",)),
   RelationRule("authorized_origin",("prefix",),("asn",)),
   RelationRule("registered_to",("prefix","asn"),("legal-entity",)),
   RelationRule("updates",("rfc",),("rfc",)),
   RelationRule("obsoletes",("rfc",),("rfc",)),
 ),
 fixtures=({"id":"RFC 4271","title":"BGP-4"},{"prefix":"203.0.113.0/24","collector":"rrc00"}),
)
