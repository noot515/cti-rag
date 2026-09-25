"""Pinned fictitious networking fixtures with documented real-world semantics."""
RFC_1771_XML=b'''<rfc number="1771" published="1995-03-01T00:00:00Z" obsoleted-by="4271">
<title>A Border Gateway Protocol 4 (BGP-4)</title>
<section number="1" title="Introduction">This document defines an earlier version of BGP-4 for exchanging reachability information.</section>
<section number="4.3" title="UPDATE Message Format">An UPDATE message advertises feasible routes and withdraws previously advertised routes.</section>
</rfc>'''
RFC_4271_XML=b'''<rfc number="4271" published="2006-01-01T00:00:00Z" obsoletes="1771">
<title>A Border Gateway Protocol 4 (BGP-4)</title>
<section number="1" title="Introduction">BGP is an inter-Autonomous System routing protocol.</section>
<section number="4.3" title="UPDATE Message Format">An UPDATE message is used to transfer routing information between BGP peers.</section>
</rfc>'''

BGP_FIXTURE=(
 {"id":"rrc00|203.0.113.0/24|2026-01-10T00:00:00Z|AS64496","prefix":"203.0.113.0/24","collector":"rrc00","vantage_point":"peer-64496","peer_asn":"AS64496","origin_asn":"AS64500","as_path":["AS64496","AS64500"],"observed_at":"2026-01-10T00:00:00Z","observed_until":"2026-01-10T01:00:00Z","available_at":"2026-01-10T00:01:00Z","version":"v1"},
 {"id":"rrc01|203.0.113.0/24|2026-01-10T00:00:00Z|AS64497","prefix":"203.0.113.0/24","collector":"rrc01","vantage_point":"peer-64497","peer_asn":"AS64497","origin_asn":"AS64501","as_path":["AS64497","AS64501"],"observed_at":"2026-01-10T00:00:00Z","observed_until":"2026-01-10T01:00:00Z","available_at":"2026-01-10T00:01:30Z","version":"v1"},
 {"id":"rrc00|203.0.113.128/25|2026-01-10T00:00:00Z|AS64496","prefix":"203.0.113.128/25","collector":"rrc00","vantage_point":"peer-64496","peer_asn":"AS64496","origin_asn":"AS64502","as_path":["AS64496","AS64502"],"observed_at":"2026-01-10T00:00:00Z","observed_until":"2026-01-10T01:00:00Z","available_at":"2026-01-10T00:01:00Z","version":"v1"},
 {"id":"rrc00|2001:db8::/32|2026-01-10T00:00:00Z|AS64496","prefix":"2001:db8::/32","collector":"rrc00","vantage_point":"peer-64496","peer_asn":"AS64496","origin_asn":"AS64510","as_path":["AS64496","AS64510"],"observed_at":"2026-01-10T00:00:00Z","observed_until":"2026-01-10T01:00:00Z","available_at":"2026-01-10T00:01:00Z","version":"v1"},
 {"id":"rrc00|2001:db8:1::/48|2026-01-10T00:00:00Z|AS64496","prefix":"2001:db8:1::/48","collector":"rrc00","vantage_point":"peer-64496","peer_asn":"AS64496","origin_asn":"AS64511","as_path":["AS64496","AS64511"],"observed_at":"2026-01-10T00:00:00Z","observed_until":"2026-01-10T01:00:00Z","available_at":"2026-01-10T00:01:00Z","version":"v1"},
 {"id":"rrc00|198.51.100.0/24|2026-02-10T00:00:00Z|AS64496","prefix":"198.51.100.0/24","collector":"rrc00","vantage_point":"peer-64496","peer_asn":"AS64496","origin_asn":"AS64520","as_path":["AS64496","AS64520"],"observed_at":"2026-02-10T00:00:00Z","observed_until":"2026-02-10T01:00:00Z","available_at":"2026-02-10T00:01:00Z","version":"v1"},
)
BGP_CORRECTED_FIXTURE=({"id":"rrc00|203.0.113.0/24|2026-01-10T00:00:00Z|AS64496","prefix":"203.0.113.0/24","collector":"rrc00","vantage_point":"peer-64496","peer_asn":"AS64496","origin_asn":"AS64509","as_path":["AS64496","AS64509"],"observed_at":"2026-01-10T00:00:00Z","observed_until":"2026-01-10T01:00:00Z","available_at":"2026-01-20T00:00:00Z","version":"v2"},)

RPKI_FIXTURE=(
 {"id":"203.0.113.0/24|25|AS64500","prefix":"203.0.113.0/24","max_length":25,"asn":"AS64500","valid_from":"2026-01-01T00:00:00Z","valid_to":"2027-01-01T00:00:00Z","available_at":"2026-01-01T00:10:00Z","version":"serial-1"},
 {"id":"2001:db8::/32|48|AS64510","prefix":"2001:db8::/32","max_length":48,"asn":"AS64510","valid_from":"2026-01-01T00:00:00Z","valid_to":"2027-01-01T00:00:00Z","available_at":"2026-01-01T00:10:00Z","version":"serial-1"},
)

DNS_FIXTURE=(
 {"id":"example.test|A|resolver-a|2026-01-10T00:00:00Z|203.0.113.7","qname":"example.test","rrtype":"A","rdata":"203.0.113.7","ttl":300,"resolver":"resolver-a","vantage_point":"lab-a","observed_at":"2026-01-10T00:00:00Z","available_at":"2026-01-10T00:00:05Z","version":"obs-1"},
 {"id":"example.test|A|resolver-a|2026-02-10T00:00:00Z|198.51.100.7","qname":"example.test","rrtype":"A","rdata":"198.51.100.7","ttl":300,"resolver":"resolver-a","vantage_point":"lab-a","observed_at":"2026-02-10T00:00:00Z","available_at":"2026-02-10T00:00:05Z","version":"obs-2"},
 {"id":"example.test|AAAA|resolver-v6|2026-01-10T00:00:00Z|2001:db8:1::7","qname":"example.test","rrtype":"AAAA","rdata":"2001:db8:1::7","ttl":600,"resolver":"resolver-v6","vantage_point":"lab-v6","observed_at":"2026-01-10T00:00:00Z","available_at":"2026-01-10T00:00:05Z","version":"obs-v6"},
)

RDAP_FIXTURE=(
 {"id":"203.0.113.0/24|EXAMPLE-NET","resource":"203.0.113.0/24","entity_handle":"EXAMPLE-NET","entity_name":"Example Network Registrant","registration_start":"2025-01-01T00:00:00Z","registration_end":None,"observed_at":"2026-01-10T00:00:00Z","available_at":"2026-01-10T00:00:05Z","version":"rdap-1"},
)
