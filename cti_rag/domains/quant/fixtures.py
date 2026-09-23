"""Fictitious point-in-time finance fixtures shaped after public SEC/FRED semantics and licensed-file imports."""
SEC_COMPANY_FIXTURE={
 "record_type":"company","cik":"0000123456","name":"Example Holdings, Inc.","available_at":"2025-01-01T00:00:00Z","version":"company-1"
}
SEC_FILING_FIXTURE={
 "record_type":"filing","cik":"0000123456","company_name":"Example Holdings, Inc.","accessionNumber":"0000123456-26-000001","form":"8-K",
 "filed":"2026-01-05","acceptanceDateTime":"2026-01-05T12:00:00Z","amendment":False,"amends":None,
 "document":{"name":"example-8k.htm","sections":[{"id":"item-1-05","title":"Item 1.05 Material Cybersecurity Incidents","text":"Example Holdings disclosed a fictitious cybersecurity incident for deterministic retrieval tests."}]},
 "facts":[{"namespace":"us-gaap","tag":"Revenues","unit":"USD","value":100.0,"period_start":"2025-10-01","period_end":"2025-12-31","reporting_basis":"US-GAAP","context_id":"ctx-revenue","currency":"USD"}],
 "version":"filing-1"
}
SEC_FILING_AMENDED_FIXTURE={
 "record_type":"filing","cik":"0000123456","company_name":"Example Holdings, Inc.","accessionNumber":"0000123456-26-000002","form":"8-K/A",
 "filed":"2026-01-20","acceptanceDateTime":"2026-01-20T12:00:00Z","amendment":True,"amends":"0000123456-26-000001",
 "document":{"name":"example-8ka.htm","sections":[{"id":"item-1-05","title":"Item 1.05 Material Cybersecurity Incidents","text":"Example Holdings amended the fictitious disclosure with corrected financial context."}]},
 "facts":[{"namespace":"us-gaap","tag":"Revenues","unit":"USD","value":105.0,"period_start":"2025-10-01","period_end":"2025-12-31","reporting_basis":"US-GAAP","context_id":"ctx-revenue","currency":"USD"}],
 "version":"filing-2"
}

FRED_ALFRED_FIXTURE={
 "series_id":"GDPX","title":"Fixture GDP Index","units":"index","frequency":"monthly","seasonal_adjustment":"not seasonally adjusted",
 "observations":[
  {"date":"2025-12-01","value":"100.0","realtime_start":"2026-01-10","realtime_end":"2026-01-31"},
  {"date":"2025-12-01","value":"110.0","realtime_start":"2026-02-01","realtime_end":"9999-12-31"}
 ]
}

PRICE_CSV_FIXTURE=b'''security_id,ticker,exchange,trading_date,close,currency,calendar,timezone,adjusted,provider,available_at,corporate_action_version
SEC-EXAMPLE,EXM,XNAS,2026-01-05,100.0,USD,XNAS,America/New_York,false,fixture-provider,2026-01-05T21:01:00Z,none
SEC-EXAMPLE,EXM,XNAS,2026-01-06,100.0,USD,XNAS,America/New_York,false,fixture-provider,2026-01-06T21:01:00Z,none
SEC-EXAMPLE,EXM,XNAS,2026-01-07,102.0,USD,XNAS,America/New_York,false,fixture-provider,2026-01-07T21:01:00Z,none
SEC-EXAMPLE,EXM,XNAS,2026-01-08,106.08,USD,XNAS,America/New_York,false,fixture-provider,2026-01-08T21:01:00Z,none
SEC-EXAMPLE,EXM,XNAS,2026-01-09,111.384,USD,XNAS,America/New_York,false,fixture-provider,2026-01-09T21:01:00Z,none
SEC-BENCH,BMK,XNAS,2026-01-05,100.0,USD,XNAS,America/New_York,false,fixture-provider,2026-01-05T21:01:00Z,none
SEC-BENCH,BMK,XNAS,2026-01-06,100.0,USD,XNAS,America/New_York,false,fixture-provider,2026-01-06T21:01:00Z,none
SEC-BENCH,BMK,XNAS,2026-01-07,101.0,USD,XNAS,America/New_York,false,fixture-provider,2026-01-07T21:01:00Z,none
SEC-BENCH,BMK,XNAS,2026-01-08,103.02,USD,XNAS,America/New_York,false,fixture-provider,2026-01-08T21:01:00Z,none
SEC-BENCH,BMK,XNAS,2026-01-09,104.0502,USD,XNAS,America/New_York,false,fixture-provider,2026-01-09T21:01:00Z,none
'''
PRICE_ADJUSTED_CSV_FIXTURE=b'''security_id,ticker,exchange,trading_date,close,currency,calendar,timezone,adjusted,provider,available_at,corporate_action_version
SEC-EXAMPLE,EXM,XNAS,2026-01-05,50.0,USD,XNAS,America/New_York,true,fixture-provider,2026-02-01T00:00:00Z,split-2-for-1
SEC-EXAMPLE,EXM,XNAS,2026-01-06,50.0,USD,XNAS,America/New_York,true,fixture-provider,2026-02-01T00:00:00Z,split-2-for-1
SEC-EXAMPLE,EXM,XNAS,2026-01-07,51.0,USD,XNAS,America/New_York,true,fixture-provider,2026-02-01T00:00:00Z,split-2-for-1
SEC-EXAMPLE,EXM,XNAS,2026-01-08,53.04,USD,XNAS,America/New_York,true,fixture-provider,2026-02-01T00:00:00Z,split-2-for-1
SEC-EXAMPLE,EXM,XNAS,2026-01-09,55.692,USD,XNAS,America/New_York,true,fixture-provider,2026-02-01T00:00:00Z,split-2-for-1
SEC-BENCH,BMK,XNAS,2026-01-05,50.0,USD,XNAS,America/New_York,true,fixture-provider,2026-02-01T00:00:00Z,rebased
SEC-BENCH,BMK,XNAS,2026-01-06,50.0,USD,XNAS,America/New_York,true,fixture-provider,2026-02-01T00:00:00Z,rebased
SEC-BENCH,BMK,XNAS,2026-01-07,50.5,USD,XNAS,America/New_York,true,fixture-provider,2026-02-01T00:00:00Z,rebased
SEC-BENCH,BMK,XNAS,2026-01-08,51.51,USD,XNAS,America/New_York,true,fixture-provider,2026-02-01T00:00:00Z,rebased
SEC-BENCH,BMK,XNAS,2026-01-09,52.0251,USD,XNAS,America/New_York,true,fixture-provider,2026-02-01T00:00:00Z,rebased
'''
CORPORATE_ACTION_CSV_FIXTURE=b'''security_id,action_type,effective_date,ratio,currency,provider,available_at
SEC-EXAMPLE,split,2026-01-15,2.0,USD,fixture-provider,2026-02-01T00:00:00Z
'''
SECURITY_MASTER_FIXTURE=(
 {"id":"SEC-OLD|XYZ|XNAS|2024-01-01","security_id":"SEC-OLD","issuer_cik":"0000999999","ticker":"XYZ","exchange":"XNAS","alias_from":"2024-01-01T00:00:00Z","alias_to":"2025-07-01T00:00:00Z","listed_from":"2024-01-01T00:00:00Z","listed_to":"2025-07-01T00:00:00Z","delisted_at":"2025-07-01T00:00:00Z","universe_id":"TEST-100","member_from":"2024-01-01T00:00:00Z","member_to":"2025-07-01T00:00:00Z","available_at":"2024-01-01T00:00:00Z","version":"sm-1"},
 {"id":"SEC-NEW|XYZ|XNAS|2025-07-01","security_id":"SEC-NEW","issuer_cik":"0000888888","ticker":"XYZ","exchange":"XNAS","alias_from":"2025-07-01T00:00:00Z","alias_to":None,"listed_from":"2025-07-01T00:00:00Z","listed_to":None,"delisted_at":None,"universe_id":"TEST-100","member_from":"2025-07-01T00:00:00Z","member_to":None,"available_at":"2025-07-01T00:00:00Z","version":"sm-2"},
 {"id":"SEC-EXAMPLE|EXM|XNAS|2025-01-01","security_id":"SEC-EXAMPLE","issuer_cik":"0000123456","ticker":"EXM","exchange":"XNAS","alias_from":"2025-01-01T00:00:00Z","alias_to":None,"listed_from":"2025-01-01T00:00:00Z","listed_to":None,"delisted_at":None,"universe_id":"TEST-100","member_from":"2025-01-01T00:00:00Z","member_to":None,"available_at":"2025-01-01T00:00:00Z","version":"sm-exm"},
)
