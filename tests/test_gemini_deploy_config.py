import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class GeminiDeployConfigTests(unittest.TestCase):
    def test_workflow_derives_secret_id_instead_of_hardcoding_project_value(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")

        self.assertNotIn("GEMINI_SECRET_ID: w-tool-utm_gemini_api-key", workflow)
        self.assertIn("GEMINI_SECRET_ID_OVERRIDE", workflow)
        self.assertIn('echo "gemini_secret_id=', workflow)
        self.assertIn('${PROJECT_ID}_gemini_api-key', workflow)

    def test_setup_script_allows_secret_id_override_per_project(self):
        setup_script = (REPO_ROOT / "infra" / "setup.sh").read_text(encoding="utf-8")

        self.assertIn('GEMINI_SECRET_ID="${GEMINI_SECRET_ID:-${PROJECT_ID}_gemini_api-key}"', setup_script)

    def test_setup_script_can_bootstrap_missing_gemini_secret(self):
        setup_script = (REPO_ROOT / "infra" / "setup.sh").read_text(encoding="utf-8")

        self.assertIn("GEMINI_API_KEY", setup_script)
        self.assertIn("read -rs", setup_script)


if __name__ == "__main__":
    unittest.main()
