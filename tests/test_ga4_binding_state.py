import unittest

from ga4_binding import build_ga4_binding_state


ACCOUNTS = [
    {
        "display_name": "Account A",
        "properties": [
            {"property_id": "properties/123456", "display_name": "Prop One"},
            {"property_id": "properties/999999", "display_name": "Prop Two"},
        ],
    }
]


class Ga4BindingStateTests(unittest.TestCase):
    def test_lock_mode_single_property_accessible(self):
        state = build_ga4_binding_state(
            lock_mode=True,
            accounts_structure=ACCOUNTS,
            configured_scope="single_property",
            configured_account_name="Account A",
            configured_allowed_properties=[{"property_id": "123456", "property_name": "Prop One"}],
            configured_default_property_id="123456",
        )

        self.assertEqual(state["ga4_scope"], "single_property")
        self.assertEqual(state["effective_property_id"], "123456")
        self.assertTrue(state["is_accessible"])
        self.assertEqual(state["reason"], "ok")

    def test_lock_mode_multi_property_rejects_external_selection(self):
        state = build_ga4_binding_state(
            lock_mode=True,
            accounts_structure=ACCOUNTS,
            configured_scope="multi_property",
            configured_account_name="Account A",
            configured_allowed_properties=[
                {"property_id": "123456", "property_name": "Prop One"},
                {"property_id": "999999", "property_name": "Prop Two"},
            ],
            configured_default_property_id="123456",
            selected_property_id="555555",
        )

        self.assertFalse(state["is_selected_allowed"])
        self.assertEqual(state["reason"], "selected_property_not_allowed")

    def test_lock_mode_multi_property_accepts_allowed_selection(self):
        state = build_ga4_binding_state(
            lock_mode=True,
            accounts_structure=ACCOUNTS,
            configured_scope="multi_property",
            configured_account_name="Account A",
            configured_allowed_properties=[
                {"property_id": "123456", "property_name": "Prop One"},
                {"property_id": "999999", "property_name": "Prop Two"},
            ],
            configured_default_property_id="123456",
            selected_property_id="999999",
        )

        self.assertTrue(state["is_selected_allowed"])
        self.assertEqual(state["effective_property_id"], "999999")
        self.assertEqual(state["reason"], "ok")

    def test_lock_mode_account_only_requires_manual_property(self):
        state = build_ga4_binding_state(
            lock_mode=True,
            accounts_structure=ACCOUNTS,
            configured_scope="account_only",
            configured_account_name="Account A",
        )

        self.assertEqual(state["reason"], "manual_property_required_for_account_scope")
        self.assertEqual(state["effective_property_id"], "")

    def test_lock_mode_none_requires_manual_property(self):
        state = build_ga4_binding_state(
            lock_mode=True,
            accounts_structure=ACCOUNTS,
            configured_scope="none",
        )

        self.assertEqual(state["reason"], "manual_property_required_for_none_scope")
        self.assertEqual(state["effective_property_id"], "")


if __name__ == "__main__":
    unittest.main()
