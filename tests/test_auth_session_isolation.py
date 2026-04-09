import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import auth


TOKEN_JSON = (
    '{"token":"access-token","refresh_token":"refresh-token","token_uri":"https://oauth2.googleapis.com/token",'
    '"client_id":"client-id","client_secret":"client-secret","scopes":["openid"]}'
)


class AuthSessionIsolationTests(unittest.TestCase):
    def test_load_credentials_restores_only_current_browser_session(self):
        cred_store = Mock()
        cred_store.load_token.return_value = TOKEN_JSON

        with patch.object(auth.st, "session_state", {"browser_session_id": "browser-123", "user_email": "alice@example.com"}):
            restored = auth.load_credentials(cred_store, Path("token.json"))

        self.assertIsNotNone(restored)
        self.assertEqual(restored.token, "access-token")
        cred_store.load_token.assert_called_once_with("browser_session:browser-123")

    def test_load_credentials_does_not_restore_without_browser_session(self):
        cred_store = Mock()

        with patch.object(auth.st, "session_state", {"user_email": "alice@example.com"}):
            restored = auth.load_credentials(cred_store, Path("token.json"))

        self.assertIsNone(restored)
        cred_store.load_token.assert_not_called()

    def test_save_credentials_persists_for_current_browser_session_only(self):
        cred_store = Mock()
        creds = Mock()
        creds.to_json.return_value = TOKEN_JSON

        with patch.object(auth.st, "session_state", {"browser_session_id": "browser-123", "user_email": "alice@example.com"}):
            auth.save_credentials(creds, cred_store, Path("token.json"))

        cred_store.save_token.assert_called_once_with("browser_session:browser-123", TOKEN_JSON)

    def test_logout_clears_browser_session_token_and_legacy_user_token(self):
        cred_store = Mock()

        with patch.object(auth.st, "session_state", {"browser_session_id": "browser-123", "user_email": "alice@example.com"}):
            auth.logout(cred_store, Path("token.json"))

        cred_store.delete_token.assert_has_calls(
            [
                call("browser_session:browser-123"),
                call("alice@example.com"),
            ],
            any_order=False,
        )


if __name__ == "__main__":
    unittest.main()
