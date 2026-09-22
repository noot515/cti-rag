from cti_rag.domains.spec import DomainSpec,IdentifierParser,RelationRule
SPEC=DomainSpec(
 name="humanities",schemas=("work/1","edition/1","passage/1","tei/1"),
 identifiers=(IdentifierParser("isbn",r"(?:97[89])?[0-9]{9}[0-9X]",True),IdentifierParser("doi",r"10\.[0-9]{4,9}/\S+")),
 query_templates=(("passage_lookup","edition-aware passage lookup"),("corpus_search","lexical+dense corpus search")),
 relation_rules=(RelationRule("edition_of",("edition",),("work",)),RelationRule("translation_of",("edition",),("edition",))),fixtures=({"work":"synthetic-work","edition":"synthetic-edition"},),
)
