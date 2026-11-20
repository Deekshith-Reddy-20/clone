import unittest

from app.services.voice.spoken_output import emergency_reply, is_emergency_utterance


class SpokenOutputTests(unittest.TestCase):
    def test_emergency_te(self) -> None:
        self.assertTrue(is_emergency_utterance("అత్యవసరం ambulance కావాలి"))
        self.assertIn("112", emergency_reply("te-IN"))


if __name__ == "__main__":
    unittest.main()