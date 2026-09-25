from dataclasses import dataclass
from typing import Tuple
@dataclass(frozen=True)
class CyberBenchmarkCase:
    case_id:str; query:str; expected_kind:str; expected_key:str; source_ids:Tuple[str,...]
CORE_CYBER_BENCHMARK=(
    CyberBenchmarkCase("cve-exact","CVE-2099-0001","exact","CVE-2099-0001",("cve-list-v5",)),
    CyberBenchmarkCase("cve-report","fictitious cross-site scripting issue","passage","CVE-2099-0001",("cve-list-v5",)),
    CyberBenchmarkCase("cve-severity","CVSS score for CVE-2099-0001","structured","cyber_cvss",("cve-list-v5",)),
    CyberBenchmarkCase("kev-status","Is CVE-2099-0001 in KEV?","structured","cyber_kev",("cisa-kev",)),
    CyberBenchmarkCase("cve-cwe-map","How is CVE-2099-0001 mapped to a weakness?","graph_path","has_weakness",("cve-list-v5",)),
)
