import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestAttackDefenseE2E(unittest.TestCase):
    def run_scenario(self, name: str) -> dict:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "kos_sim",
                "run",
                "--scenario",
                name,
                "--format",
                "json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}")
        return json.loads(proc.stdout)

    def test_defender_playbook_blocks_objective(self) -> None:
        report = self.run_scenario("defender_playbook")
        self.assertFalse(report["objective_reached"])
        self.assertEqual(report["winner"], "defender")
        self.assertNotIn("db", report["compromised_assets"])

    def test_attacker_chain_reaches_objective(self) -> None:
        report = self.run_scenario("attacker_chain")
        self.assertTrue(report["objective_reached"])
        self.assertEqual(report["winner"], "attacker")
        self.assertIn("db", report["compromised_assets"])


if __name__ == "__main__":
    unittest.main()

