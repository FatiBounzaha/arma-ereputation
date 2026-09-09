from pathlib import Path

from backend.services.facebook_screenshot_service import load_facebook_urls


def test_current_collector_reads_facebook_links(tmp_path: Path):
    links = tmp_path / "fb.txt"
    links.write_text(
        "https://www.facebook.com/Page/posts/123\n"
        "https://www.youtube.com/watch?v=abc123\n",
        encoding="utf-8",
    )
    assert load_facebook_urls(links) == ["https://www.facebook.com/Page/posts/123"]
