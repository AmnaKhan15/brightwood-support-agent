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

    def test_vercel_routes_api_to_python_and_the_rest_to_the_website(self):
        config = json.loads((ROOT / "vercel.json").read_text())
        api, web = config["services"]["api"], config["services"]["web"]
        self.assertEqual((api["root"], api["entrypoint"], web["root"]), (".", "app:app", "web"))
        self.assertNotIn("data/", api["functions"]["app.py"]["excludeFiles"])  # the help articles must ship
        # Most specific first: /api/* to the API (which keeps the /api prefix its routes expect), then everything else.
        self.assertEqual([(r["source"], r["destination"]["service"]) for r in config["rewrites"]],
                         [("/api/(.*)", "api"), ("/(.*)", "web")])

    def test_stripe_returns_to_the_vercel_site_by_default(self):
        from brightwood_support.service import Service
        self.assertEqual(Service(env={"VERCEL_PROJECT_PRODUCTION_URL": "brightwood.vercel.app"}).site_url, "https://brightwood.vercel.app")
        self.assertEqual(Service(env={"VERCEL_PROJECT_PRODUCTION_URL": "x.vercel.app", "SITE_URL": "https://shop.example/"}).site_url,
                         "https://shop.example")


if __name__ == "__main__":
    unittest.main()
