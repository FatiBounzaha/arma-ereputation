from backend.services.facebook_retained_links_service import is_public_facebook_url


def test_only_public_facebook_links_without_secrets_are_accepted():
    assert is_public_facebook_url("https://www.facebook.com/Page/posts/123") is True
    assert is_public_facebook_url("https://example.com/Page/posts/123") is False
    assert is_public_facebook_url("https://facebook.com/Page/posts/123?access_token=secret") is False
    assert is_public_facebook_url("javascript:alert(1)") is False


def test_facebook_urls_are_found_inside_serper_payload_and_redirects():
    from backend.services.facebook_url_utils import extract_facebook_publication_urls

    payload = {
        "organic": [
            {
                "link": "https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.facebook.com%2Farma.page%2Fposts%2F123%3Fref%3Dshare"
            }
        ]
    }
    assert extract_facebook_publication_urls(payload) == [
        "https://www.facebook.com/arma.page/posts/123"
    ]


def test_story_permalink_keeps_required_identifiers():
    from backend.services.facebook_url_utils import extract_facebook_publication_urls

    urls = extract_facebook_publication_urls(
        "https://m.facebook.com/story.php?story_fbid=456&id=789&ref=share"
    )
    assert urls == [
        "https://www.facebook.com/story.php?story_fbid=456&id=789"
    ]
