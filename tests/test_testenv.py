"""`src/testenv.py` — środowisko testowe PO na Kubernetes, bez prawdziwego klastra.

Polecenia (git/podman/kind/helm/kubectl) są przechwytywane; sprawdzamy, CO aplikacja
by wykonała. Prawdziwe wdrożenie na kind-preprod sprawdza przebieg E2E.
"""

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import testenv

VALUES = """\
services:
  shop-catalog:
    image: localhost/shop-catalog:0.0.1
  shop-ui:
    image: localhost/shop-ui:0.0.1
"""


class TestEnvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        Path(self.tmp.name, "shop-infra", "helm").mkdir(parents=True)
        Path(self.tmp.name, "shop-infra", "helm", "values.yaml").write_text(VALUES, encoding="utf-8")
        env = mock.patch.dict(os.environ, {"SHOP_REPOS_DIR": self.tmp.name, "SHOPQA_TMP": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.commands: list[list[str]] = []

    def _fake_run(self, fail_on: str = ""):
        def run(cmd, log, timeout=1800, env=None):
            self.commands.append(cmd)
            return not (fail_on and fail_on in " ".join(cmd))
        return run

    def _deploy(self, changes, fail_on=""):
        with mock.patch.object(testenv, "_run", side_effect=self._fake_run(fail_on)), \
                mock.patch.object(testenv, "start_links",
                                  return_value={"urls": {"ui": "http://localhost:1", "api": "http://localhost:2"},
                                                "pids": {"ui": 11, "api": 12}}), \
                mock.patch.object(testenv, "links_alive", return_value={"ui": True, "api": True}):
            return testenv.deploy_test_env(changes, namespace="test-ns")

    def test_only_chart_services_are_built_and_deployed(self):
        changes = {
            "shop-catalog": {"repo_path": "C:/r/shop-catalog", "files": [{"path": "A.java", "content": "x"}]},
            "shop-acceptance-tests": {"repo_path": "C:/r/acc", "files": [{"path": "B.feature", "content": "y"}]},
        }
        env = self._deploy(changes)

        self.assertTrue(env["success"], env["error"])
        self.assertEqual({"shop-catalog": "localhost/shop-catalog:test-ns"}, env["images"])
        self.assertEqual(["shop-acceptance-tests"], env["skipped"])
        builds = [c for c in self.commands if c[:2] == ["podman", "build"]]
        self.assertEqual(1, len(builds), "testy akceptacyjne nie są obrazem do wdrożenia")
        helm = next(c for c in self.commands if c[0] == "helm")
        self.assertIn("test-ns", helm)
        self.assertIn("--create-namespace", helm)
        self.assertIn("services.shop-catalog.image=localhost/shop-catalog:test-ns", helm)
        self.assertIn("observability.enabled=false", helm)
        self.assertEqual({"ui": "http://localhost:1", "api": "http://localhost:2"}, env["urls"])

    def test_change_without_deployable_service_is_reported_not_deployed(self):
        env = self._deploy({"shop-acceptance-tests": {"repo_path": "C:/r/acc", "files": []}})

        self.assertFalse(env["success"])
        self.assertIn("nie dotyczy", env["error"])
        self.assertEqual([], self.commands, "nic nie powinno być budowane ani wdrażane")

    def test_failed_build_stops_before_touching_the_cluster(self):
        env = self._deploy({"shop-ui": {"repo_path": "C:/r/ui", "files": []}}, fail_on="podman build")

        self.assertFalse(env["success"])
        self.assertIn("shop-ui", env["error"])
        self.assertFalse(any(c[0] in ("kind", "helm") for c in self.commands))

    def test_destroy_stops_links_and_deletes_the_namespace(self):
        env = {"namespace": "test-ns", "pids": {"ui": 11}, "images": {"shop-ui": "localhost/shop-ui:test-ns"}}
        with mock.patch.object(testenv, "_run", side_effect=self._fake_run()), \
                mock.patch.object(testenv, "_stop_pids") as stop:
            self.assertTrue(testenv.destroy_test_env(env))

        stop.assert_called_once_with({"ui": 11})
        self.assertIn(["kubectl", "--context", testenv.CONTEXT, "delete", "namespace", "test-ns", "--wait=false"],
                      self.commands)

    def test_namespace_is_a_valid_dns_label(self):
        ns = testenv.new_namespace()
        self.assertRegex(ns, r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
        self.assertLessEqual(len(ns), 63)
        self.assertNotEqual(ns, testenv.new_namespace())


if __name__ == "__main__":
    unittest.main()
