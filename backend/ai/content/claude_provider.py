from __future__ import annotations

import os

from dotenv import load_dotenv

from backend.ai.content.base import PostContentProvider, PostDraft
from backend.ai.content.safety import prepare_and_validate_post_payload
from backend.ai.json_utils import extract_json_object, positive_int_env

try:
    import anthropic
except ImportError:  # pragma: no cover - dépend de l'environnement d'exécution
    anthropic = None

load_dotenv()

DEFAULT_MODEL_NAME = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = (
    "Tu es le rédacteur du portail interne d'ARMA, entreprise marocaine de "
    "propreté urbaine. Tu produis uniquement des BROUILLONS bilingues fondés "
    "sur les preuves fournies. Tu réponds avec un objet JSON valide, sans "
    "markdown ni texte autour, au format exact : "
    '{"fr": {"body": "texte en français", "hashtags": ["#Tag1", "#Tag2"]}, '
    '"ar": {"body": "texte en arabe", "hashtags": ["#Tag1"]}, '
    '"image_prompt": "description visuelle en français", '
    '"tone": ["adjectif1", "adjectif2"]}. '
    "RÈGLES FACTUELLES OBLIGATOIRES : "
    "1) N'invente aucun chiffre, contrat, ville, client, ancienneté, distinction, "
    "performance, technologie ou intervention. "
    "2) N'écris jamais qu'ARMA garantit un résultat, agit sans interruption, "
    "est leader, est reconnue par des partenaires ou que des collectivités lui "
    "font confiance sans preuve explicite. "
    "3) Si les preuves sont sectorielles et ne décrivent pas une action d'ARMA, "
    "parle de tendance, d'enjeu ou d'ambition avec des verbes prudents : "
    "mobilise, souhaite, peut contribuer, s'engage à étudier. "
    "4) Le prompt image ne doit pas inventer un logo, un uniforme ou un site ARMA. "
    "5) Le français doit être entièrement français et l'arabe fluide. "
    "6) Adapte la longueur : X très concis, LinkedIn professionnel, Instagram et "
    "Facebook visuels. Place les hashtags uniquement dans les tableaux hashtags."
)


class ClaudePostProvider(PostContentProvider):
    """Rédige un brouillon bilingue via l'API Claude puis le valide localement."""

    def __init__(self, model_name: str | None = None) -> None:
        if anthropic is None:
            raise RuntimeError(
                "Le paquet 'anthropic' n'est pas installé. Lancez : pip install anthropic"
            )

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key == "your_anthropic_api_key":
            raise RuntimeError(
                "ANTHROPIC_API_KEY est absente ou vide dans le fichier .env. "
                "Renseignez une clé valide ou utilisez POST_CONTENT_PROVIDER=template."
            )

        self.model_name = model_name or DEFAULT_MODEL_NAME
        self._client = anthropic.Anthropic(api_key=api_key)

    def write_post(
        self,
        organization_name: str,
        platform: str,
        angle_title: str,
        angle_description: str,
        evidence_snippets: list[str],
    ) -> PostDraft:
        evidence_text = (
            "\n".join(f"- {snippet}" for snippet in evidence_snippets)
            or "Aucune preuve spécifique fournie."
        )

        user_prompt = (
            f"Organisation : {organization_name}\n"
            f"Plateforme : {platform}\n"
            f"Angle stratégique : {angle_title}\n"
            f"Description de l'angle : {angle_description}\n\n"
            "Éléments de preuve autorisés (ne rien affirmer au-delà) :\n"
            f"{evidence_text}\n\n"
            "Le contenu doit rester un brouillon prudent soumis à validation humaine."
        )

        attempts = positive_int_env("LLM_MAX_RETRIES", 2, maximum=5) + 1
        max_tokens = positive_int_env(
            "POST_MAX_TOKENS", 1000, minimum=400, maximum=4000
        )
        last_error: Exception | None = None
        retry_feedback = ""

        for attempt in range(1, attempts + 1):
            response = self._client.messages.create(
                model=self.model_name,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_prompt + retry_feedback},
                ],
            )
            try:
                payload = parse_response_payload(response.content[0].text)
                payload = prepare_and_validate_post_payload(
                    payload,
                    platform=platform,
                    evidence_text=evidence_text,
                    angle_title=angle_title,
                    angle_description=angle_description,
                )
                return build_result_from_payload(
                    payload=payload,
                    platform=platform,
                    model_name=self.model_name,
                    model_version=response.model,
                )
            except RuntimeError as error:
                last_error = error
                retry_feedback = (
                    "\n\nLa proposition précédente a été refusée par le contrôle qualité : "
                    f"{str(error)[:1000]}\nCorrige tous ces points et renvoie uniquement le JSON."
                )
                print(
                    f"Réponse Claude post invalide, tentative {attempt}/{attempts} : {error}"
                )

        raise RuntimeError(
            f"Claude n'a pas renvoyé un JSON sûr après {attempts} tentatives : {last_error}"
        )


def parse_response_payload(raw_output: str) -> dict:
    """Parse une sortie Claude en tolérant les fences et le texte parasite."""
    try:
        return extract_json_object(raw_output)
    except RuntimeError as error:
        raise RuntimeError(
            "Réponse Claude non exploitable (JSON invalide ou tronqué)."
        ) from error


def build_result_from_payload(
    payload: dict,
    platform: str,
    model_name: str,
    model_version: str | None,
) -> PostDraft:
    if "fr" not in payload or "ar" not in payload:
        raise RuntimeError(
            f"Réponse Claude incomplète, 'fr'/'ar' manquant : {payload}"
        )

    return PostDraft(
        content_by_language={"fr": payload["fr"], "ar": payload["ar"]},
        image_prompt=payload.get("image_prompt"),
        tone=payload.get("tone", []),
        model_provider="anthropic",
        model_name=model_name,
        model_version=model_version,
        details={**payload, "platform": platform, "quality_checked": True},
    )


def test_parse_response() -> None:
    valid_response = (
        '{"fr": {"body": "ARMA mobilise ses équipes.", "hashtags": ["#ARMA"]}, '
        '"ar": {"body": "تعبئ أرما فرقها.", "hashtags": ["#أرما"]}, '
        '"image_prompt": "Photo urbaine neutre au Maroc", '
        '"tone": ["professionnel"]}'
    )
    payload = parse_response_payload(valid_response)
    result = build_result_from_payload(
        payload=payload,
        platform="linkedin",
        model_name="test-model",
        model_version="test-version",
    )
    print(result)


if __name__ == "__main__":
    test_parse_response()
