"""Small redistribution-safe humanities fixtures.

The Gutenberg fixture uses a short public-domain U.S. passage from ebook 1342,
with Project Gutenberg trademark/license boilerplate excluded from the embedded
text. The TEI and IIIF records are synthetic source-shaped metadata fixtures.
"""
import json

GUTENBERG_WORK={
 "record_type":"work","id":"WORK:AUSTEN-PP","title":"Pride and Prejudice","creator":"Jane Austen",
 "language":"en","rights":"public-domain-us","source_uri":"https://www.gutenberg.org/ebooks/1342",
 "available_at":"2026-01-01T00:00:00Z","version":"work-1"
}
GUTENBERG_EDITION={
 "record_type":"edition","id":"EDITION:PP-GUTENBERG-1342","work_id":"WORK:AUSTEN-PP",
 "label":"Project Gutenberg ebook 1342 text fixture","language":"en","rights":"public-domain-us",
 "source_uri":"https://www.gutenberg.org/ebooks/1342",
 "date_interval":{"start":"1813-01-28","end_exclusive":"1813-01-29","precision":"exact_date","label":"1813-01-28"},
 "available_at":"2026-01-01T00:00:00Z","version":"edition-1",
 "passages":[
  {"id":"PASSAGE:PP-OPENING-GUT","role":"primary_text","ordinal":1,
   "original":"It is a truth universally acknowledged, that a single man in possession of a good fortune must be in want of a wife.",
   "normalized":"It is a truth universally acknowledged, that a single man in possession of a good fortune must be in want of a wife.",
   "language":"en","transcription_quality":"manual","locator":{"kind":"canonical","scheme":"gutenberg-paragraph","value":"1342:chapter-1:p1"},
   "alignment":[{"original_start":0,"original_end":116,"normalized_start":0,"normalized_end":116,"confidence":1.0}]},
  {"id":"ANNOTATION:PP-GUT-1","role":"editorial_annotation","ordinal":2,
   "original":"editorial secret phrase only in annotation","normalized":"editorial secret phrase only in annotation",
   "language":"en","transcription_quality":"editorial","locator":{"kind":"canonical","scheme":"fixture-note","value":"1342:note-1"},
   "alignment":[{"original_start":0,"original_end":41,"normalized_start":0,"normalized_end":41,"confidence":1.0}]}
 ]
}
GUTENBERG_COMPARISON_EDITION={
 "record_type":"edition","id":"EDITION:PP-COMPARISON-FIXTURE","work_id":"WORK:AUSTEN-PP",
 "label":"Synthetic comparison edition over public-domain text","language":"en","rights":"public-domain-test-derivative",
 "source_uri":"fixture:pp-comparison",
 "date_interval":{"start":"1813-01-01","end_exclusive":"1814-01-01","precision":"year","label":"1813"},
 "available_at":"2026-01-01T00:00:00Z","version":"edition-compare-1",
 "passages":[
  {"id":"PASSAGE:PP-OPENING-COMPARE","role":"primary_text","ordinal":1,
   "original":"It is a truth universally acknowledged that a single man, possessed of good fortune, must be in want of a wife.",
   "normalized":"It is a truth universally acknowledged that a single man, possessed of good fortune, must be in want of a wife.",
   "language":"en","transcription_quality":"manual","locator":{"kind":"canonical","scheme":"fixture-edition","value":"pp-compare:1"},
   "alignment":[{"original_start":0,"original_end":108,"normalized_start":0,"normalized_end":108,"confidence":1.0}]}
 ]
}

TEI_PERSEUS_STYLE_FIXTURE=b'''<TEI work_id="WORK:VIRGIL-AENEID" edition_id="EDITION:AENEID-LATIN-FIXTURE" witness_id="WITNESS:AENEID-LATIN-1" language="la" rights="public-domain-ancient-text" available_at="2026-01-01T00:00:00Z">
 <teiHeader><fileDesc><titleStmt><title>Aeneid fixture</title></titleStmt></fileDesc></teiHeader>
 <text><body><div type="book" n="1">
  <l n="1" xml:id="urn:cts:latinLit:phi0690.phi003:1.1">Arma virumque cano</l>
  <note type="editorial">editorial apparatus phrase not primary text</note>
 </div></body></text>
 <translation edition_id="EDITION:AENEID-EN-TRANSLATION-FIXTURE" language="en" source_edition="EDITION:AENEID-LATIN-FIXTURE">
  <seg n="1">I sing of arms and the man</seg>
 </translation>
</TEI>'''

IIIF_NEWSPAPER_FIXTURE={
 "record_type":"newspaper","id":"EDITION:NEWS-1900-FIXTURE","work_id":"WORK:NEWS-FIXTURE",
 "article_id":"ARTICLE:RAIL-STATION-FIXTURE","page_id":"PAGE:NEWS-1900-1","institution_id":"INSTITUTION:FIXTURE-LIBRARY",
 "label":"Synthetic 1900 newspaper/IIIF fixture","language":"en",
 "rights":"public-domain-shaped-fixture","rights_statement":"Modeled on Chronicling America public-domain/no-known-restrictions metadata; text is synthetic.",
 "date_interval":{"start":"1900-06-01","end_exclusive":"1900-07-01","precision":"month","label":"June 1900 (month known; day unknown)"},
 "available_at":"2026-01-01T00:00:00Z","version":"iiif-1",
 "canvas_id":"https://example.invalid/iiif/canvas/news-1900-p1","page":1,"bbox":[100.0,200.0,900.0,600.0],
 "passages":[
  {"id":"PASSAGE:NEWS-RAIL-1","role":"primary_text","ordinal":1,
   "original":"The Railr0ad stat1on re-opened after repairs on Tuesday.",
   "normalized":"The Railroad station reopened after repairs on Tuesday.",
   "language":"en","transcription_quality":"ocr","ocr_confidence":0.72,
   "alignment":[{"original_start":0,"original_end":55,"normalized_start":0,"normalized_end":53,"confidence":0.72}]},
  {"id":"ANNOTATION:NEWS-1","role":"editorial_annotation","ordinal":2,
   "original":"modern archive annotation phrase only","normalized":"modern archive annotation phrase only",
   "language":"en","transcription_quality":"editorial",
   "alignment":[{"original_start":0,"original_end":37,"normalized_start":0,"normalized_end":37,"confidence":1.0}]}
 ]
}

GUTENBERG_ROWS=(GUTENBERG_WORK,GUTENBERG_EDITION,GUTENBERG_COMPARISON_EDITION)
