import unittest

from app.services.voice.voice_sentence_chunker import SentenceChunker


class SentenceChunkerTests(unittest.TestCase):
    def test_splits_on_telugu_danda(self) -> None:
        c = SentenceChunker(min_words=2)
        parts = c.feed("Hello world. మీకు సహాయం చేస్తాను। More text here now")
        flushed = c.flush()
        joined = " ".join(parts + flushed)
        self.assertIn("సహాయం", joined)