import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import auth


class AuthSessionIsolationTests(unittest.TestCase):
    def test_load_credentials_does_not_restore_server_side_tokens(self):
        cred_store = Mock()
        cred_store.load_token.return_value = (
            '{"token":"access-token","refresh_token":"refresh-token","token_uri":"https://oauth2.googleapis.com/token",'
            '"client_id":"client-id","client_secret":"client-secret","scopes":["openid"]}'
        )

        with patch.object(auth.st, "session_state", {"user_email": "alice@example.com"}):
            restored = auth.load_credentials(cred_store, Path("token.json"))

        self.assertIsNone(restored)
        cred_store.load_token.assert_not_called()

    def test_save_credentials_does_not_persist_tokens_for_future_sessions(self):
        cred_store = Mock()
        creds = Mock()

        with patch.object(auth.st, "session_state", {"user_email": "alice@example.com"}):
            auth.save_credentials(creds, cred_store, Path("token.json"))

        cred_store.save_token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
