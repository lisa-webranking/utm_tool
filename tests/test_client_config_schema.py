import unittest

from storage import ClientConfigError, validate_client_config


class ClientConfigSchemaTests(unittest.TestCase):
    def test_legacy_single_property_is_backfilled(self):
        cfg, _warnings = validate_client_config(
            {
                "client_id": "test_client",
                "version": 1,
                "ga4_client_name": "Account A",
                "ga4_property_id": "123456",
                "ga4_property_name": "Prop One",
            }
        )

        self.assertEqual(cfg.ga4_scope, "single_property")
        self.assertEqual(cfg.ga4_account_name, "Account A")
        self.assertEqual(cfg.ga4_default_property_id, "123456")
        self.assertEqual(len(cfg.ga4_allowed_properties), 1)
        self.assertEqual(cfg.ga4_allowed_properties[0]["property_id"], "123456")

    def test_multi_property_infers_default_from_first_allowed(self):
        cfg, _warnings = validate_client_config(
            {
                "client_id": "test_client",
                "version": 1,
                "ga4_scope": "multi_property",
                "ga4_account_name": "Account A",
                "ga4_allowed_properties": [
                    {"property_id": "123456", "property_name": "Prop One"},
                    {"property_id": "999999", "property_name": "Prop Two"},
                ],
            }
        )

        self.assertEqual(cfg.ga4_default_property_id, "123456")

    def test_multi_property_invalid_default_raises(self):
        with self.assertRaises(ClientConfigError):
            validate_client_config(
                {
                    "client_id": "test_client",
                    "version": 1,
                    "ga4_scope": "multi_property",
                    "ga4_account_name": "Account A",
                    "ga4_default_property_id": "555555",
                    "ga4_allowed_properties": [
                        {"property_id": "123456", "property_name": "Prop One"},
                        {"property_id": "999999", "property_name": "Prop Two"},
                    ],
                }
            )

    def test_none_scope_allows_missing_ga4(self):
        cfg, _warnings = validate_client_config(
            {
                "client_id": "test_client",
                "version": 1,
                "ga4_scope": "none",
            }
        )

        self.assertEqual(cfg.ga4_scope, "none")
        self.assertEqual(cfg.ga4_default_property_id, "")
        self.assertEqual(cfg.ga4_allowed_properties, [])


if __name__ == "__main__":
    unittest.main()
