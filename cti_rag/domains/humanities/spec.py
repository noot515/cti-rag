from cti_rag.domains.spec import DomainSpec,IdentifierParser,RelationRule
SPEC=DomainSpec(
 name="humanities",
 schemas=("humanities-work/1","humanities-edition/1","tei-document/1","iiif-newspaper/1","humanities-passage/1"),
 identifiers=(
   IdentifierParser("work-id",r"WORK:[A-Z0-9._-]+",True),
   IdentifierParser("edition-id",r"EDITION:[A-Z0-9._-]+",True),
   IdentifierParser("passage-id",r"PASSAGE:[A-Z0-9._:-]+",True),
   IdentifierParser("cts",r"urn:cts:[^\s]+"),
   IdentifierParser("isbn",r"(?:97[89])?[0-9]{9}[0-9X]",True),
   IdentifierParser("doi",r"10\.[0-9]{4,9}/\S+"),
 ),
 query_templates=(
   ("work_lookup","exact work lookup"),
   ("edition_lookup","exact edition lookup"),
   ("passage_lookup","edition-aware exact passage lookup"),
   ("quotation","primary-text phrase lookup returning original transcription"),
   ("corpus_search","lexical+dense primary-text explanation"),
   ("date_interval","structured overlap query over uncertain/approximate source dates"),
   ("edition_compare","deterministic comparison preserving both edition coordinates"),
   ("source_criticism","separate primary text, editorial annotation, scholarship, and interpretation"),
 ),
 relation_rules=(
   RelationRule("edition_of",("edition",),("work",)),
   RelationRule("witness_of",("witness",),("edition",)),
   RelationRule("translation_of",("edition",),("edition",)),
   RelationRule("article_on_page",("article",),("page",)),
   RelationRule("held_by",("edition","page","article"),("institution",)),
 ),
 fixtures=(
   {"work":"WORK:AUSTEN-PP","edition":"EDITION:PP-GUTENBERG-1342","language":"en"},
   {"work":"WORK:VIRGIL-AENEID","edition":"EDITION:AENEID-LATIN-FIXTURE","language":"la"},
 ),
)
