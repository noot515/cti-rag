from __future__ import annotations
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

from cti_rag.composition.feature_flags import RetrievalFeatureFlags
from cti_rag.contracts import AccessLabel,ProcessingClass
from cti_rag.policy.local import PublicOnlyLocalPolicy
from cti_rag.ports import AuthenticatedPrincipal,ClientScopeRequest,PolicyDenied
from cti_rag.release import load_requirement_matrix,load_source_readiness,milestone_readiness

ROOT=Path(__file__).resolve().parents[1]

class Phase24ReleaseConformanceTests(unittest.TestCase):
    def test_matrix_accounts_for_all_25_sections_and_preserves_blocked_milestones(self):
        matrix=load_requirement_matrix(ROOT/"validation"/"revised-plan-conformance.json",ROOT)
        self.assertEqual(list(range(1,26)),[row["section"] for row in matrix["sections"]])
        fixture=milestone_readiness(matrix,"fixture_core")
        text=milestone_readiness(matrix,"text_mvp")
        five=milestone_readiness(matrix,"five_domain")
        release=milestone_readiness(matrix,"full_release")
        self.assertEqual("passed",fixture["status"])
        self.assertEqual("blocked",text["status"])
        self.assertEqual("blocked",five["status"])
        self.assertEqual("blocked",release["status"])
        self.assertIn("section-18-primary",five["blocking_requirements"])

    def test_source_readiness_does_not_equate_registry_with_adapter(self):
        data=load_source_readiness(ROOT/"validation"/"source-readiness.json")
        by_id={row["source_id"]:row for row in data["sources"]}
        self.assertGreaterEqual(len(by_id),48)
        self.assertEqual("passed",by_id["mitre-attack-stix"]["adapter_status"])
        self.assertEqual("blocked",by_id["nvd"]["adapter_status"])
        self.assertEqual("not_run",by_id["nvd"]["fixture_lifecycle"])
        self.assertEqual("blocked",by_id["privacy-core"]["manifest_status"])
        self.assertEqual("blocked",by_id["privacy-core"]["adapter_status"])

    def test_optional_integrations_default_disabled_and_public_policy_cannot_enable_private_placeholder(self):
        names=("CTI_RAG_ADVANCED_RETRIEVAL_ENABLED","CTI_RAG_WEB_OVERLAY_ENABLED")
        old={name:os.environ.pop(name,None) for name in names}
        try:flags=RetrievalFeatureFlags.from_env()
        finally:
            for name,value in old.items():
                if value is not None:os.environ[name]=value
        self.assertFalse(flags.advanced_retrieval_enabled);self.assertFalse(flags.web_overlay_enabled);self.assertTrue(flags.legacy_endpoints_enabled)
        provider=PublicOnlyLocalPolicy.build("fixture-user",("cybersecurity",))
        principal=AuthenticatedPrincipal("fixture-user","public")
        request=ClientScopeRequest(("cybersecurity",),access_labels=(AccessLabel.PRIVATE,),processing_classes=(ProcessingClass.LOCAL_ONLY,))
        with self.assertRaises(PolicyDenied):provider.authorize(principal,request)

    def test_isolated_migration_rehearsal_covers_switch_query_rollback_deletion_and_restore(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);report=td/"migration-report.json"
            proc=subprocess.run([sys.executable,str(ROOT/"scripts"/"phase24_migration_rehearsal.py"),"--root",str(td/"runtime"),"--backup",str(td/"backup"),"--report",str(report)],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(0,proc.returncode,proc.stderr)
            row=json.loads(report.read_text())
            self.assertFalse(row["legacy_default"]["advanced_retrieval_enabled"])
            self.assertTrue(row["legacy_default"]["legacy_endpoints_enabled"])
            self.assertEqual("ok",row["legacy_default"]["query_status"])
            self.assertTrue(row["feature_switch"]["advanced_retrieval_enabled"])
            self.assertTrue(row["feature_switch"]["legacy_endpoints_enabled"])
            self.assertEqual("ok",row["new_generation"]["query_status"])
            self.assertEqual("ok",row["rollback"]["query_status"])
            self.assertEqual("empty",row["deletion"]["query_status_after_revocation"])
            self.assertTrue(row["backup_restore"]["revocation_preserved"])
            self.assertFalse(row["optional_components"]["web_overlay_enabled"])
            self.assertFalse(row["optional_components"]["opencti_required_for_core"])
            self.assertFalse(row["optional_components"]["external_runtimepolicy_required_for_public_local_core"])

    def test_conformance_cli_writes_blocked_release_without_failing_fixture_core(self):
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/"conformance.json"
            proc=subprocess.run([sys.executable,str(ROOT/"scripts"/"run_phase24_conformance.py"),"--report",str(report)],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(0,proc.returncode,proc.stderr)
            row=json.loads(report.read_text())
            self.assertEqual(25,row["sections_accounted"])
            self.assertGreaterEqual(row["source_count"],48)
            self.assertEqual("passed",row["milestones"]["fixture_core"]["status"])
            self.assertEqual("blocked",row["milestones"]["text_mvp"]["status"])
            self.assertEqual("blocked",row["milestones"]["five_domain"]["status"])
            self.assertEqual("blocked",row["milestones"]["full_release"]["status"])

if __name__=="__main__":unittest.main()
