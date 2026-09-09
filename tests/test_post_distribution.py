import os
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from types import SimpleNamespace

from backend.ai.content.post_service import build_angle_platform_pairs


def test_eight_posts_cover_four_platforms():
    angles = [SimpleNamespace(id=i) for i in range(4)]
    pairs = build_angle_platform_pairs(angles, 8, ["linkedin", "instagram", "facebook", "x"])
    assert len(pairs) == 8
    assert {platform for _, platform in pairs} == {"linkedin", "instagram", "facebook", "x"}


def test_target_count_is_kept_with_only_one_angle():
    angles = [SimpleNamespace(id=1)]
    pairs = build_angle_platform_pairs(angles, 8, ["linkedin", "instagram", "facebook", "x"])
    assert len(pairs) == 8
    assert {platform for _, platform in pairs} == {"linkedin", "instagram", "facebook", "x"}
