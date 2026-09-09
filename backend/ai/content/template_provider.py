from __future__ import annotations

from backend.ai.content.base import PostContentProvider, PostDraft
from backend.ai.content.safety import sanitize_post_payload

PLATFORM_TONE: dict[str, list[str]] = {
    "linkedin": ["professionnel", "factuel"],
    "instagram": ["visuel", "engageant"],
    "facebook": ["accessible", "communautaire"],
    "x": ["concis", "factuel"],
}

SAFE_FR_TEXT: dict[str, str] = {
    "Stabilité & performance": (
        "Dans un secteur en évolution, la continuité et la qualité opérationnelle "
        "restent des priorités pour les acteurs de la propreté urbaine. ARMA mobilise "
        "ses équipes et suit ces enjeux afin de contribuer à des services urbains fiables."
    ),
    "Partenariat public-privé": (
        "Les nouveaux marchés de propreté rappellent l'importance d'un dialogue structuré "
        "entre collectivités et opérateurs. ARMA suit ces évolutions et met son expérience "
        "métier au service de solutions adaptées, sous réserve de validation des références."
    ),
    "Conformité & transparence": (
        "La traçabilité et le respect des exigences environnementales deviennent centraux. "
        "ARMA suit ces évolutions pour renforcer une communication factuelle et responsable."
    ),
    "Innovation urbaine durable": (
        "Les solutions numériques, circulaires et bas-carbone transforment le secteur de la "
        "propreté urbaine. ARMA suit ces tendances et évalue les approches pertinentes pour "
        "les besoins des villes."
    ),
    "Ancrage marocain durable": (
        "Les villes marocaines font face à des enjeux de propreté différents selon leur "
        "territoire. ARMA valorise une lecture locale des besoins et une approche de proximité."
    ),
}

SAFE_AR_TEXT: dict[str, str] = {
    "Stabilité & performance": (
        "في قطاع يشهد تطورات متواصلة، تظل استمرارية الخدمة وجودة الأداء من الأولويات. "
        "تعبئ أرما فرقها وتتابع هذه التحديات للمساهمة في خدمات حضرية موثوقة."
    ),
    "Partenariat public-privé": (
        "تؤكد مشاريع النظافة الجديدة أهمية التعاون المنظم بين الجماعات والفاعلين. "
        "تتابع أرما هذه التطورات وتضع خبرتها المهنية في خدمة حلول ملائمة بعد التحقق من المعطيات."
    ),
    "Conformité & transparence": (
        "أصبحت الشفافية وتتبع الأداء واحترام المتطلبات البيئية عناصر أساسية. "
        "تتابع أرما هذه التطورات من أجل تواصل مسؤول ومبني على معطيات موثوقة."
    ),
    "Innovation urbaine durable": (
        "تغير الحلول الرقمية والدائرية والمنخفضة الكربون قطاع النظافة الحضرية. "
        "تتابع أرما هذه التوجهات وتدرس المقاربات الملائمة لحاجيات المدن."
    ),
    "Ancrage marocain durable": (
        "تختلف تحديات النظافة بين المدن المغربية حسب خصوصيات كل مجال. "
        "تعتمد أرما قراءة محلية للحاجيات ومقاربة قائمة على القرب."
    ),
}


def build_hashtag(organization_name: str) -> str:
    return "#" + organization_name.replace(" ", "")


class TemplatePostProvider(PostContentProvider):
    """Gabarit bilingue prudent utilisé seulement comme secours technique."""

    def write_post(
        self,
        organization_name: str,
        platform: str,
        angle_title: str,
        angle_description: str,
        evidence_snippets: list[str],
    ) -> PostDraft:
        hashtag = build_hashtag(organization_name)
        fr_body = SAFE_FR_TEXT.get(
            angle_title,
            "ARMA suit les évolutions du secteur de la propreté urbaine et prépare une "
            "communication factuelle, soumise à validation interne.",
        )
        ar_body = SAFE_AR_TEXT.get(
            angle_title,
            "تتابع أرما تطورات قطاع النظافة الحضرية وتعد تواصلا مبنيا على معطيات موثوقة وخاضعا للتحقق الداخلي.",
        )

        if platform == "x":
            fr_body = fr_body[:205].rstrip(" ,;:-") + "."
            ar_body = ar_body[:205].rstrip(" ،؛:-") + "."

        payload = sanitize_post_payload(
            {
                "fr": {"body": fr_body, "hashtags": [hashtag, "#Maroc"]},
                "ar": {"body": ar_body, "hashtags": [hashtag, "#المغرب"]},
                "image_prompt": (
                    f"Photographie institutionnelle neutre au Maroc illustrant « {angle_title} » : "
                    "espace urbain propre, équipe professionnelle en tenue neutre, matériel de "
                    "propreté non marqué, lumière naturelle, aucun logo ni texte inventé."
                ),
                "tone": PLATFORM_TONE.get(platform, ["factuel"]),
            },
            platform,
        )

        return PostDraft(
            content_by_language={"fr": payload["fr"], "ar": payload["ar"]},
            image_prompt=payload["image_prompt"],
            tone=payload["tone"],
            model_provider="template",
            model_name="post-template-bilingual-v3-safe",
            model_version="3",
            details={
                "platform": platform,
                "evidence_count": len(evidence_snippets),
                "fallback": True,
                "quality_checked": True,
            },
        )
