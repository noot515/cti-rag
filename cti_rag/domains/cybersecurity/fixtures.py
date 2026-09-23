"""Small fictitious records encoded in real upstream formats for offline lifecycle validation."""
ATTACK_STIX_FIXTURE=b'''{
  "type":"bundle","id":"bundle--00000000-0000-4000-8000-000000000001",
  "objects":[
    {"type":"attack-pattern","spec_version":"2.1","id":"attack-pattern--00000000-0000-4000-8000-000000000101",
     "created":"2026-01-01T00:00:00.000Z","modified":"2026-01-02T00:00:00.000Z",
     "name":"Fixture Script Interpreter","description":"Fictitious ATT&CK-format technique used only for parser tests.",
     "external_references":[{"source_name":"mitre-attack","external_id":"T9001"}],
     "x_mitre_version":"1.0","x_mitre_deprecated":false,"revoked":false},
    {"type":"relationship","spec_version":"2.1","id":"relationship--00000000-0000-4000-8000-000000000201",
     "created":"2026-01-01T00:00:00.000Z","modified":"2026-01-02T00:00:00.000Z",
     "relationship_type":"related-to",
     "source_ref":"attack-pattern--00000000-0000-4000-8000-000000000101",
     "target_ref":"attack-pattern--00000000-0000-4000-8000-000000000101",
     "description":"Fixture self relation; traversal cycle controls must suppress it.","revoked":false}
  ]
}'''
ATTACK_STIX_REVOKED_FIXTURE=b'''{
  "type":"bundle","id":"bundle--00000000-0000-4000-8000-000000000002",
  "objects":[
    {"type":"attack-pattern","spec_version":"2.1","id":"attack-pattern--00000000-0000-4000-8000-000000000101",
     "created":"2026-01-01T00:00:00.000Z","modified":"2026-02-02T00:00:00.000Z",
     "name":"Fixture Script Interpreter","description":"Revoked fixture revision.",
     "external_references":[{"source_name":"mitre-attack","external_id":"T9001"}],
     "x_mitre_version":"2.0","x_mitre_deprecated":false,"revoked":true}
  ]
}'''
INVALID_STIX_FIXTURE=b'{"type":"bundle","objects":[{"type":"attack-pattern","id":"bad"}]}'

CVE_V5_FIXTURE=b'''{
 "dataType":"CVE_RECORD","dataVersion":"5.2",
 "cveMetadata":{"cveId":"CVE-2099-0001","state":"PUBLISHED","datePublished":"2026-01-03T00:00:00.000Z","dateUpdated":"2026-01-03T00:00:00.000Z"},
 "containers":{"cna":{
   "descriptions":[{"lang":"en","value":"Fictitious cross-site scripting issue for parser tests."}],
   "problemTypes":[{"descriptions":[{"lang":"en","type":"CWE","cweId":"CWE-79","description":"CWE-79"}]}],
   "metrics":[{"cvssV3_1":{"version":"3.1","baseScore":8.8,"baseSeverity":"HIGH","vectorString":"CVSS:3.1/AV:N/AC:L/PR:L/UI:R/S:U/C:H/I:H/A:H"}}]
 }}
}'''
CVE_V5_UPDATED_FIXTURE=b'''{
 "dataType":"CVE_RECORD","dataVersion":"5.2",
 "cveMetadata":{"cveId":"CVE-2099-0001","state":"PUBLISHED","datePublished":"2026-01-03T00:00:00.000Z","dateUpdated":"2026-02-03T00:00:00.000Z"},
 "containers":{"cna":{
   "descriptions":[{"lang":"en","value":"Updated fictitious cross-site scripting issue for parser tests."}],
   "problemTypes":[{"descriptions":[{"lang":"en","type":"CWE","cweId":"CWE-79","description":"CWE-79"}]}],
   "metrics":[{"cvssV3_1":{"version":"3.1","baseScore":9.8,"baseSeverity":"CRITICAL","vectorString":"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}}]
 }}
}'''

KEV_FIXTURE=b'''{
 "title":"Fixture Known Exploited Vulnerabilities Catalog","catalogVersion":"2099.01.01","dateReleased":"2026-01-05T00:00:00.000Z","count":1,
 "vulnerabilities":[{
   "cveID":"CVE-2099-0001","vendorProject":"Fixture Vendor","product":"Fixture Product",
   "vulnerabilityName":"Fixture exploited vulnerability","dateAdded":"2026-01-05",
   "shortDescription":"Fictitious KEV-format entry for parser tests.","requiredAction":"Apply vendor mitigations.",
   "dueDate":"2026-01-26","knownRansomwareCampaignUse":"Unknown","notes":"fixture"
 }]
}'''
