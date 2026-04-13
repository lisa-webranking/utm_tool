import unittest

import chatbot_ui


class ChatbotGa4LockModeTests(unittest.TestCase):
    def test_system_instruction_in_lock_mode_blocks_property_switch(self):
        context = {
            "current_step": 0,
            "params": {},
            "ga4_property_id": "123456",
        }
        instruction = chatbot_ui._build_system_instruction(
            context,
            current_date="2026-04-13",
            preferred_property_id="123456",
            preferred_property_name="Client Property",
            ga4_binding_state={
                "lock_mode": True,
                "is_accessible": False,
                "reason": "configured_property_not_accessible",
            },
        )

        self.assertIn("PROPERTY CLIENTE VINCOLATA (LOCK ATTIVO)", instruction)
        self.assertIn("NON accettare property alternative", instruction)
        self.assertIn("PROPERTY GA4: LOCK CLIENTE ATTIVO", instruction)

    def test_system_instruction_in_lock_mode_multi_property_uses_effective_property(self):
        context = {
            "current_step": 0,
            "params": {},
            "ga4_property_id": "999999",
        }
        instruction = chatbot_ui._build_system_instruction(
            context,
            current_date="2026-04-13",
            preferred_property_id="999999",
            preferred_property_name="Prop Two",
            ga4_binding_state={
                "lock_mode": True,
                "ga4_scope": "multi_property",
                "is_accessible": True,
                "reason": "ok",
            },
        )

        self.assertIn("PROPERTY CLIENTE VINCOLATA (LOCK ATTIVO)", instruction)
        self.assertIn("properties/999999", instruction)


if __name__ == "__main__":
    unittest.main()
