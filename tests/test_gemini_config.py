import os
import unittest
from unittest.mock import Mock

import googleapi


class SharedGeminiConfigTests(unittest.TestCase):
    def test_shared_key_prefers_environment_variable(self):
        config_value = Mock(return_value="config-key")

        with unittest.mock.patch.dict(os.environ, {"GEMINI_API_KEY": "env-key"}, clear=False):
            resolved = googleapi.get_shared_gemini_api_key(config_value)

        self.assertEqual(resolved, "env-key")
        config_value.assert_not_called()

    def test_shared_key_falls_back_to_config_reader(self):
        config_value = Mock(side_effect=lambda name: "config-key" if name == "GEMINI_API_KEY" else "")

        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            resolved = googleapi.get_shared_gemini_api_key(config_value)

        self.assertEqual(resolved, "config-key")

    def test_shared_key_returns_empty_string_when_missing(self):
        config_value = Mock(return_value="")

        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            resolved = googleapi.get_shared_gemini_api_key(config_value)

        self.assertEqual(resolved, "")


if __name__ == "__main__":
    unittest.main()
