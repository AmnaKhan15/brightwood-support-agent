"""The deployment files agree with each other and the Vercel entry point loads."""
import importlib.util
import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DeployConfigTests(unittest.TestCase):
    def test_pyproject_and_requirements_list_the_same_dependencies(self):
        reqs = [line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["dependencies"], reqs)

    def test_vercel_entry_point_serves_the_api(self):
        spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "app.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        paths = {route.path for route in module.app.routes}
        self.assertTrue({"/api/chat", "/api/tts", "/api/health"} <= paths)

    def test_vercel_config_points_at_the_entry_point(self):
        config = json.loads((ROOT / "vercel.json").read_text())
        self.assertIn("app.py", config["functions"])
        self.assertNotIn("data/", config["functions"]["app.py"]["excludeFiles"])  # the help articles must ship


if __name__ == "__main__":
    unittest.main()
