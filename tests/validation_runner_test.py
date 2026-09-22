import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ValidationRunnerTests(unittest.TestCase):
    def run_registry(self, gates):
        root = Path(__file__).resolve().parents[1]
        with tempfile.NamedTemporaryFile("w", suffix=".json", dir=root, delete=False) as handle:
            json.dump({"schema_version": "validation-registry/1", "gates": gates}, handle)
            path = Path(handle.name)
        try:
            return subprocess.run(
                [sys.executable, str(root / "scripts/validate_phases.py"), "--through-phase", "1", "--registry", path.name],
                cwd=root, text=True, capture_output=True,
            )
        finally:
            path.unlink(missing_ok=True)

    def test_required_blocked_gate_fails_overall(self):
        result = self.run_registry([{"id": "blocked", "phase": 0, "required": True, "status_override": "blocked", "reason": "no service"}])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"status": "blocked"', result.stdout)

    def test_required_not_run_gate_fails_overall(self):
        result = self.run_registry([{"id": "not-run", "phase": 0, "required": True, "status_override": "not_run", "reason": "not executed"}])
        self.assertNotEqual(result.returncode, 0)

    def test_optional_blocked_gate_does_not_fail_overall(self):
        result = self.run_registry([{"id": "optional", "phase": 0, "required": False, "status_override": "blocked", "reason": "optional dependency"}])
        self.assertEqual(result.returncode, 0)

    def test_failed_command_is_not_pass(self):
        result = self.run_registry([{"id": "fails", "phase": 1, "required": True, "command": f"{sys.executable} -c \"raise SystemExit(3)\""}])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('"status": "fail"', result.stdout)

    def test_passing_command_passes(self):
        result = self.run_registry([{"id": "passes", "phase": 1, "required": True, "command": f"{sys.executable} -c \"print('ok')\""}])
        self.assertEqual(result.returncode, 0)
        self.assertIn('"status": "pass"', result.stdout)


if __name__ == "__main__":
    unittest.main()
