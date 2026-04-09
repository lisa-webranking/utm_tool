import unittest

import chatbot_ui


class ChatbotGeminiRuntimeTests(unittest.TestCase):
    def test_chatbot_prefers_current_gemini_models(self):
        self.assertEqual(chatbot_ui.CHATBOT_GEMINI_MODELS[0], "gemini-2.5-flash")
        self.assertIn("gemini-flash-latest", chatbot_ui.CHATBOT_GEMINI_MODELS)
        self.assertNotIn("gemini-1.5-flash", chatbot_ui.CHATBOT_GEMINI_MODELS)
        self.assertNotIn("gemini-1.5-pro", chatbot_ui.CHATBOT_GEMINI_MODELS)
        self.assertNotIn("gemini-2.0-flash", chatbot_ui.CHATBOT_GEMINI_MODELS)

    def test_invalid_key_message_does_not_reference_removed_settings_ui(self):
        message = chatbot_ui._classify_gemini_error(Exception("invalid api key"))

        self.assertNotIn("impostazioni", message.lower())
        self.assertIn("amministratore", message.lower())

    def test_model_not_found_message_is_actionable(self):
        message = chatbot_ui._classify_gemini_error(
            Exception("404 model not found for generateContent")
        )

        self.assertIn("modello", message.lower())
        self.assertIn("amministratore", message.lower())


if __name__ == "__main__":
    unittest.main()
