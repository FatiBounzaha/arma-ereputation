from __future__ import annotations

from pathlib import Path

from backend.services.apify_facebook_comments_service import (
    apify_integration_status,
    build_actor_input,
    load_retained_facebook_urls,
    normalize_apify_item,
    run_apify_actor,
    sanitize_apify_raw_payload,
)
from backend.services.facebook_comment_collection_service import comments_collection_status


def test_build_actor_input_uses_supported_fields_and_final_all_comments_mode(monkeypatch):
    monkeypatch.setenv("APIFY_MAX_COMMENTS_PER_POST", "20")
    monkeypatch.setenv("APIFY_ALL_COMMENTS_LIMIT", "500")
    monkeypatch.setenv("APIFY_COLLECT_ALL_COMMENTS", "true")
    monkeypatch.setenv("APIFY_INCLUDE_REPLIES", "true")
    monkeypatch.setenv("APIFY_COMMENTS_MODE", "All")
    payload = build_actor_input(["https://www.facebook.com/page/posts/123"])
    assert payload == {
        "startUrls": [{"url": "https://www.facebook.com/page/posts/123"}],
        "resultsLimit": 500,
        "includeNestedComments": True,
        "viewOption": "RECENT_ACTIVITY",
    }


def test_build_actor_input_can_opt_out_of_all_comments_mode(monkeypatch):
    monkeypatch.setenv("APIFY_MAX_COMMENTS_PER_POST", "20")
    monkeypatch.setenv("APIFY_COLLECT_ALL_COMMENTS", "false")
    monkeypatch.setenv("APIFY_INCLUDE_REPLIES", "true")
    monkeypatch.setenv("APIFY_COMMENTS_MODE", "All")
    payload = build_actor_input(["https://www.facebook.com/page/posts/123"])
    assert payload["resultsLimit"] == 20
    assert payload["viewOption"] == "RANKED_UNFILTERED"


def test_load_retained_urls_ignores_comments_and_duplicates(tmp_path: Path):
    path = tmp_path / "fb.txt"
    path.write_text(
        "# commentaire\n"
        "https://m.facebook.com/page/posts/123/?utm_source=x\n"
        "https://www.facebook.com/page/posts/123\n"
        "https://example.com/not-facebook\n",
        encoding="utf-8",
    )
    assert load_retained_facebook_urls(path) == [
        "https://www.facebook.com/page/posts/123"
    ]


def test_normalize_apify_item_maps_public_comment_fields():
    item = {
        "inputUrl": "https://www.facebook.com/page/posts/123",
        "facebookUrl": "https://www.facebook.com/page/posts/123",
        "commentUrl": "https://www.facebook.com/page/posts/123?comment_id=456",
        "commentId": "456",
        "date": "2026-08-04T10:20:00.000Z",
        "text": "La collecte est en retard.",
        "profileName": "Nom public",
        "profileId": "profile-1",
        "likesCount": "8",
        "threadingDepth": 0,
        "facebookId": "123",
        "postTitle": "Publication test",
    }
    result = normalize_apify_item(item)
    assert result is not None
    assert result["comment_id"] == "456"
    assert result["text"] == "La collecte est en retard."
    assert result["likes"] == 8
    assert result["author_name"] == "Nom public"
    assert result["post_url"] == "https://www.facebook.com/page/posts/123"
    assert result["published_at"].year == 2026


def test_apify_status_requires_token(monkeypatch):
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    state = apify_integration_status()
    assert state["available"] is False
    monkeypatch.setenv("APIFY_API_TOKEN", "apify_api_test")
    state = apify_integration_status()
    assert state["available"] is True


def test_auto_provider_prefers_apify(monkeypatch):
    monkeypatch.setenv("FACEBOOK_COMMENTS_PROVIDER", "auto")
    monkeypatch.setenv("APIFY_API_TOKEN", "apify_api_test")
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    state = comments_collection_status()
    assert state["provider"] == "apify"
    assert state["collection_available"] is True


def test_run_actor_uses_bearer_header_not_query_token(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = "[]"

        def raise_for_status(self):
            return None

        def json(self):
            return [{"commentId": "1", "text": "ok"}]

    def fake_post(url, *, params, headers, json, timeout):
        captured.update(
            {"url": url, "params": params, "headers": headers, "json": json, "timeout": timeout}
        )
        return FakeResponse()

    monkeypatch.setenv("APIFY_API_TOKEN", "secret-test-token")
    monkeypatch.setenv("APIFY_FACEBOOK_ACTOR_ID", "apify/facebook-comments-scraper")
    monkeypatch.setattr(
        "backend.services.apify_facebook_comments_service.requests.post",
        fake_post,
    )
    items = run_apify_actor(["https://www.facebook.com/page/posts/123"])
    assert items[0]["commentId"] == "1"
    assert "secret-test-token" not in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer secret-test-token"
    assert "apify~facebook-comments-scraper" in captured["url"]


def test_raw_payload_minimizes_profile_data_by_default(monkeypatch):
    monkeypatch.delenv("APIFY_STORE_PROFILE_URLS", raising=False)
    payload = sanitize_apify_raw_payload({
        "commentId": "1",
        "profileName": "Public Name",
        "profileUrl": "https://facebook.com/profile",
        "profilePicture": "https://image",
        "pageAdLibrary": {"id": "x"},
    })
    assert payload["profileName"] == "Public Name"
    assert "profileUrl" not in payload
    assert "profilePicture" not in payload
    assert "pageAdLibrary" not in payload
