import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from backend.services.social_collection_service_v2 import (  # noqa: E402
    build_social_queries,
    classify_social_object,
)


class SocialRulesTests(unittest.TestCase):
    def test_facebook_story_is_post(self):
        url = "https://www.facebook.com/story.php?story_fbid=1478372787652842&id=100064404053249"
        self.assertEqual(classify_social_object("Facebook", url), "post")

    def test_all_platforms_have_queries(self):
        for platform in ("Facebook", "Instagram", "LinkedIn", "X"):
            self.assertGreater(len(build_social_queries("ARMA", platform)), 0)


if __name__ == "__main__":
    unittest.main()
