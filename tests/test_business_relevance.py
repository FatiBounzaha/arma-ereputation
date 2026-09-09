import unittest

from backend.processing.business_relevance import evaluate_business_relevance


class BusinessRelevanceTests(unittest.TestCase):
    def test_hr_profile_is_hidden(self):
        decision = evaluate_business_relevance(
            {
                "title": "Soufiane Jakani a rejoint Suez en 2019 où il a occupé plusieurs postes",
                "snippet": "Parcours professionnel et nomination chez Suez.",
                "date": "27 juillet 2026",
            },
            organizations=["Suez Maroc"],
            sector_topics=[],
        )
        self.assertFalse(decision.display_in_marketing)
        self.assertIn("noise_or_hr_content", decision.quality_flags)

    def test_competitor_financial_signal_is_kept(self):
        decision = evaluate_business_relevance(
            {
                "title": "OZONE : le tribunal refuse d'étendre le redressement aux filiales",
                "snippet": "Le groupe de propreté urbaine traverse des difficultés financières.",
                "date": "27 juillet 2026",
            },
            organizations=["OZONE"],
            sector_topics=["proprete-urbaine"],
            query_category="competitor",
        )
        self.assertTrue(decision.display_in_marketing)
        self.assertEqual(decision.category, "competitor")
        self.assertGreaterEqual(decision.score, 0.62)

    def test_tender_is_opportunity(self):
        decision = evaluate_business_relevance(
            {
                "title": "Casablanca lance un appel d'offres pour la collecte des déchets",
                "snippet": "Un nouveau marché public de propreté urbaine est en préparation.",
                "date": "27 juillet 2026",
            },
            sector_topics=["appel-offres", "proprete-urbaine"],
            query_category="opportunity",
        )
        self.assertTrue(decision.display_in_marketing)
        self.assertEqual(decision.category, "opportunity")


if __name__ == "__main__":
    unittest.main()
