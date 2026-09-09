from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from backend.ai.comment_triage.service import triage_social_comments
from backend.ai.content.angle_service import generate_strategic_angles
from backend.ai.content.post_service import generate_posts_for_proposed_angles
from backend.ai.response_drafts.service import generate_response_drafts_for_open_alerts
from backend.ai.sentiment.service import analyze_pending_mentions
from backend.alerts.service import generate_alerts_for_negative_mentions
from backend.processing.language_detection import detect_pending_languages
from backend.processing.qualify_existing_mentions import qualify_mentions
from backend.processing.text_cleaner import clean_mentions
from backend.processing.topic_tagging import tag_mentions_with_topics
from backend.scoring.service import compute_reputation_snapshots
from backend.services.business_intelligence_collection_service import collect_business_intelligence
from backend.services.collection_service import collect_serper_news
from backend.services.facebook_comment_collection_service import collect_facebook_comments
from backend.services.facebook_retained_links_service import export_retained_facebook_links_step
from backend.services.facebook_screenshot_service import capture_retained_facebook_posts_step
from backend.services.instagram_comment_collection_service import collect_instagram_comments
from backend.services.rss_collection_service import collect_rss_mentions
from backend.services.social_collection_service_v2 import collect_social_posts_v2
from backend.services.web_collection_service import collect_serper_web
from backend.services.x_api_collection_service import collect_x_api_posts


@dataclass(frozen=True)
class OrchestrationStep:
    key: str
    name: str
    phase: str
    run: Callable[[], Any]


# Registre partagé par l'orchestrateur Python et par l'API appelée depuis n8n.
# L'ordre est volontairement stable : collecte -> traitement -> NLP -> réputation
# -> contenu marketing.
ORCHESTRATION_STEPS: tuple[OrchestrationStep, ...] = (
    OrchestrationStep("collect_serper_news", "Collecte Serper ARMA (actualités)", "collecte", collect_serper_news),
    OrchestrationStep("collect_serper_web", "Collecte Serper ARMA (web)", "collecte", collect_serper_web),
    OrchestrationStep("collect_rss", "Collecte RSS (presse marocaine)", "collecte", collect_rss_mentions),
    OrchestrationStep("collect_business_intelligence", "Veille stratégique qualifiée", "collecte", collect_business_intelligence),
    OrchestrationStep("collect_social_posts", "Découverte sociale Facebook/Instagram/LinkedIn/X", "collecte", collect_social_posts_v2),
    OrchestrationStep("collect_x_api", "Complément X API", "collecte", collect_x_api_posts),
    OrchestrationStep("collect_instagram_comments", "Commentaires Instagram ARMA", "collecte", collect_instagram_comments),
    OrchestrationStep("qualify_mentions", "Qualification métier et anti-bruit", "traitement", qualify_mentions),
    OrchestrationStep("export_facebook_retained_links", "Export des posts Facebook retenus", "evidence", export_retained_facebook_links_step),
    OrchestrationStep("collect_facebook_comments", "Commentaires Facebook publics (Apify/Meta)", "collecte", lambda: collect_facebook_comments(strict=True)),
    OrchestrationStep("clean_texts", "Nettoyage des textes", "traitement", clean_mentions),
    OrchestrationStep("detect_languages", "Détection langue FR/AR/darija", "traitement", detect_pending_languages),
    OrchestrationStep("triage_comments", "Tri intelligent des commentaires", "traitement", triage_social_comments),
    OrchestrationStep("tag_topics", "Classement par thème", "nlp", tag_mentions_with_topics),
    OrchestrationStep("analyze_sentiment", "Analyse de sentiment", "nlp", analyze_pending_mentions),
    OrchestrationStep("compute_reputation", "Calcul du score de réputation", "reputation", compute_reputation_snapshots),
    OrchestrationStep("generate_alerts", "Génération des alertes", "reputation", generate_alerts_for_negative_mentions),
    OrchestrationStep("capture_facebook_screenshots", "Captures des posts Facebook publics", "evidence", capture_retained_facebook_posts_step),
    OrchestrationStep("generate_response_drafts", "Brouillons de réponse", "reputation", lambda: generate_response_drafts_for_open_alerts(replace_existing=True)),
    OrchestrationStep("generate_angles", "Angles stratégiques", "marketing", generate_strategic_angles),
    OrchestrationStep("generate_posts", "Génération des posts", "marketing", generate_posts_for_proposed_angles),
)

STEP_BY_KEY: dict[str, OrchestrationStep] = {step.key: step for step in ORCHESTRATION_STEPS}
