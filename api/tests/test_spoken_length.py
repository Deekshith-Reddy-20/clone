import unittest

from app.services.voice.spoken_length import cap_spoken_reply


class SpokenLengthTests(unittest.TestCase):
    def test_first_sentence(self) -> None:
        long = "గదులు ఉన్నాయి. చెక్-ఇన్ తేదీ చెప్పండి మరియు ఇంకా చాలా సమాచారం."
        out = cap_spoken_reply(long, max_chars=80)
        self.assertLessEqual(len(out), 80)
        self.assertIn("గదులు", out)
        self.assertTrue(out.endswith((".", "?", "!", "।")))

    def test_never_slices_a_word(self) -> None:
        long = (
            "ఒక్క క్షణం, నవంబర్ 22 నుంచి నవంబర్ 24 వరకు 35 మందికి స్టే ఉందో చూస్తాను. "
            "నవంబర్ 22 నుంచి నవంబర్ 24 వరకు 35 మందికి గదులు లభ్యంగా ఉన్నట్లు కనిపించాయి. "
            "బుక్ చేయనా?"
        )
        out = cap_spoken_reply(long, max_chars=90)
        self.assertFalse(out.endswith("కని"))
        self.assertNotIn("కని", out)
        self.assertTrue(out.endswith((".", "?", "!", "।")))


if __name__ == "__main__":
    unittest.main()