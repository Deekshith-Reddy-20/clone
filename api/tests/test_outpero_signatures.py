import hashlib
import hmac
import time
import unittest

from app.services.outpero.signatures import mask_secret, verify_outpero_signature


class OutperoSignatureTests(unittest.TestCase):
    def test_valid_signature(self) -> None:
        secret = "whsec_test"
        body = b'{"event":"call.ended","call_id":"c_1"}'
        ts = str(int(time.time()))
        digest = hmac.new(
            secret.encode(),
            f"{ts}.".encode() + body,
            hashlib.sha256,
        ).hexdigest()
        self.assertTrue(
            verify_outpero_signature(
                secret=secret,
                timestamp=ts,
                signature_header=f"sha256={digest}",
                raw_body=body,
            )
        )

    def test_invalid_signature(self) -> None:
        self.assertFalse(
            verify_outpero_signature(
                secret="whsec_test",
                timestamp=str(int(time.time())),
                signature_header="sha256=deadbeef",
                raw_body=b"{}",
            )
        )

    def test_stale_timestamp(self) -> None:
        secret = "whsec_test"
        body = b"{}"
        ts = str(int(time.time()) - 10_000)
        digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        self.assertFalse(
            verify_outpero_signature(
                secret=secret,
                timestamp=ts,
                signature_header=f"sha256={digest}",
                raw_body=body,
                max_age_seconds=300,
            )
        )

    def test_mask_secret(self) -> None:
        masked = mask_secret("abcdefghij")
        assert masked is not None
        self.assertTrue(masked.endswith("ghij"))
        self.assertIn("*", masked)


if __name__ == "__main__":
    unittest.main()
