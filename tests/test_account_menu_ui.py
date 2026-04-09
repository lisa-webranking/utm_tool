import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class AccountMenuUiTests(unittest.TestCase):
    def test_dashboard_account_menu_does_not_render_settings_controls(self):
        app_text = (REPO_ROOT / "app.py").read_text(encoding="utf-8")

        self.assertNotIn("settings_btn_menu", app_text)
        self.assertNotIn("settings_btn_menu_fallback", app_text)
        self.assertNotIn("show_settings", app_text)
        self.assertNotIn("### Impostazioni", app_text)

    def test_dashboard_account_menu_still_renders_logout_controls(self):
        app_text = (REPO_ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn('key="logout_btn"', app_text)
        self.assertIn('key="logout_btn_fallback"', app_text)


if __name__ == "__main__":
    unittest.main()
