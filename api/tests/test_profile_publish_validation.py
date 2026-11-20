import unittest

from app.services.profile_publish_validation import validate_profile_publishable


class ProfilePublishValidationTests(unittest.TestCase):
    def test_blocks_test_only_fixture(self) -> None:
        profile = {"test_only": True, "business": {"name": "X"}}
        errs = validate_profile_publishable(profile)
        self.assertTrue(errs)

    def test_blocks_seed_source(self) -> None:
        profile = {
            "sources": [{"url": "seed", "page": "vfarms_fixture", "field": "manual"}],
        }
        self.assertTrue(validate_profile_publishable(profile))