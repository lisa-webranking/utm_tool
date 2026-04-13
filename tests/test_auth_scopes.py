import importlib
import sys
import types
import unittest
from unittest.mock import patch


def _load_auth_module():
    streamlit_stub = types.ModuleType("streamlit")
    streamlit_stub.session_state = {}
    streamlit_stub.secrets = {}
    google_stub = types.ModuleType("google")
    google_oauth2_stub = types.ModuleType("google.oauth2")
    google_credentials_stub = types.ModuleType("google.oauth2.credentials")

    class DummyCredentials:
        pass

    google_credentials_stub.Credentials = DummyCredentials
    google_oauth2_stub.credentials = google_credentials_stub
    google_stub.oauth2 = google_oauth2_stub

    with patch.dict(
        sys.modules,
        {
            "streamlit": streamlit_stub,
            "google": google_stub,
            "google.oauth2": google_oauth2_stub,
            "google.oauth2.credentials": google_credentials_stub,
        },
    ):
        sys.modules.pop("auth", None)
        return importlib.import_module("auth")


class AuthScopesTests(unittest.TestCase):
    def test_google_oauth_uses_single_read_scope_with_identity_scopes(self):
        auth = _load_auth_module()

        self.assertEqual(
            tuple(auth.SCOPES),
            (
                "https://www.googleapis.com/auth/analytics.readonly",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile",
                "openid",
            ),
        )


if __name__ == "__main__":
    unittest.main()
