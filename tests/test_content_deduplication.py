from backend.processing.content_deduplication import rank_and_deduplicate, title_similarity


def test_similar_titles_are_grouped():
    items = [
        {"title": "Casablanca lance un appel d'offres pour la collecte des déchets", "summary": "", "category": "opportunity", "relevance_score": 0.9, "published_at": "2026-07-31", "source_name": "Le360", "url": "https://example.com/a"},
        {"title": "Appel d'offres à Casablanca pour la collecte des déchets", "summary": "", "category": "opportunity", "relevance_score": 0.85, "published_at": "2026-07-31", "source_name": "TelQuel", "url": "https://example.com/b"},
    ]
    assert title_similarity(items[0]["title"], items[1]["title"]) > 0.6
    grouped = rank_and_deduplicate(items, limit=8, similarity_threshold=0.6)
    assert len(grouped) == 1
    assert grouped[0]["duplicate_count"] == 2
    assert len(grouped[0]["related_sources"]) == 2


def test_local_signal_is_prioritized():
    items = [
        {"title": "Marché de déchets à Brazzaville", "summary": "", "category": "sector", "relevance_score": 0.9, "published_at": "2026-07-31"},
        {"title": "Collecte des déchets à Casablanca Maroc", "summary": "", "category": "sector", "relevance_score": 0.8, "published_at": "2026-07-31"},
    ]
    assert rank_and_deduplicate(items, limit=2)[0]["title"].endswith("Maroc")
