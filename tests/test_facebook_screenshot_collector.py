from pathlib import Path

from backend.services.facebook_url_utils import (
    canonicalize_facebook_url,
    is_facebook_publication_url,
)
from backend.services.facebook_screenshot_service import load_facebook_urls


def test_supported_facebook_post_formats_are_accepted():
    assert is_facebook_publication_url("https://www.facebook.com/Page/posts/123")
    assert is_facebook_publication_url(
        "https://www.facebook.com/story.php?story_fbid=123&id=456"
    )
    assert is_facebook_publication_url("https://www.facebook.com/reel/123")
    assert is_facebook_publication_url("https://fb.watch/abc123/")


def test_non_posts_and_secrets_are_rejected():
    assert not is_facebook_publication_url("https://www.facebook.com/Page")
    assert not is_facebook_publication_url("https://example.com/Page/posts/123")
    assert not is_facebook_publication_url(
        "https://www.facebook.com/Page/posts/123?access_token=secret"
    )


def test_canonicalization_removes_tracking_but_keeps_post_identifiers():
    value = (
        "http://m.facebook.com/story.php?story_fbid=123&id=456"
        "&fbclid=tracking&utm_source=test"
    )
    assert canonicalize_facebook_url(value) == (
        "https://www.facebook.com/story.php?story_fbid=123&id=456"
    )


def test_fb_file_keeps_only_unique_supported_urls(tmp_path: Path):
    path = tmp_path / "fb.txt"
    path.write_text(
        "# commentaire\n"
        "https://www.facebook.com/Page/posts/123?fbclid=test\n"
        "https://facebook.com/Page/posts/123\n"
        "https://example.com/nope\n",
        encoding="utf-8",
    )
    assert load_facebook_urls(path) == ["https://www.facebook.com/Page/posts/123"]
