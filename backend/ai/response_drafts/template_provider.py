from __future__ import annotations

from typing import Any

from backend.ai.response_drafts.base import (
    ResponseDraftProvider,
    ResponseDraftResult,
)
from backend.ai.response_drafts.decision import (
    ResponseDecision,
    decide_response_action,
)


def _place_phrase_fr(place: str | None) -> str:
    return f" concernant {place}" if place else ""


def _place_phrase_ar(place: str | None) -> str:
    return f" بخصوص الوضع في {place}" if place else ""


def _build_public_reply(
    organization_name: str,
    decision: ResponseDecision,
) -> tuple[str, str, list[str]]:
    place_fr = _place_phrase_fr(decision.place_hint)
    place_ar = _place_phrase_ar(decision.place_hint)

    if decision.ask_for_private_details:
        fr = (
            f"Bonjour, merci pour votre signalement. L'équipe {organization_name} va vérifier la situation. "
            "Pouvez-vous nous envoyer en message privé le lieu exact, un repère et, si possible, une photo afin de faciliter l'intervention ?"
        )
        ar = (
            f"السلام عليكم، شكراً على التبليغ. سيقوم فريق {organization_name} بالتحقق من الوضع. "
            "المرجو إرسال المكان بالتحديد ومعلم قريب، وإن أمكن صورة، عبر رسالة خاصة لتسهيل التدخل."
        )
    else:
        fr = (
            f"Bonjour, merci pour votre signalement{place_fr}. L'équipe {organization_name} va vérifier la situation avec les équipes concernées. "
            "Vous pouvez nous transmettre en message privé un repère précis ou une photo pour faciliter le suivi."
        )
        ar = (
            f"السلام عليكم، شكراً على التبليغ{place_ar}. سيقوم فريق {organization_name} بالتحقق من الوضع مع الفرق المعنية. "
            "يمكنكم إرسال معلم دقيق أو صورة عبر رسالة خاصة لتسهيل المتابعة."
        )

    return fr, ar, ["empathique", "opérationnel", "prudent"]


def _build_official_statement(
    organization_name: str,
    decision: ResponseDecision,
) -> tuple[str, str, list[str]]:
    place_fr = _place_phrase_fr(decision.place_hint)
    place_ar = _place_phrase_ar(decision.place_hint)
    fr = (
        f"{organization_name} a pris connaissance des informations relayées{place_fr}. "
        "Les éléments évoqués font l'objet d'une vérification auprès des équipes et parties concernées. "
        "Toute communication externe sera fondée sur des informations confirmées et validées."
    )
    ar = (
        f"أخذت {organization_name} علماً بالمعلومات المتداولة{place_ar}. "
        "ويجري التحقق من العناصر المذكورة مع الفرق والأطراف المعنية. "
        "وسيتم اعتماد معطيات مؤكدة ومصادق عليها في أي تواصل خارجي."
    )
    return fr, ar, ["factuel", "institutionnel", "prudent"]


def _build_monitoring_note(
    organization_name: str,
    decision: ResponseDecision,
) -> tuple[str, str, list[str]]:
    place_fr = _place_phrase_fr(decision.place_hint)
    place_ar = _place_phrase_ar(decision.place_hint)
    fr = (
        f"Merci d'avoir relayé cette préoccupation{place_fr}. {organization_name} la prend en considération et la transmet aux équipes concernées pour vérification. "
        "Aucune réponse publique immédiate n'est recommandée avant confirmation des faits."
    )
    ar = (
        f"شكراً على نقل هذا الانشغال{place_ar}. تأخذه {organization_name} بعين الاعتبار وستحيله على الفرق المعنية للتحقق. "
        "لا يُنصح برد علني فوري قبل التأكد من المعطيات."
    )
    return fr, ar, ["factuel", "à vérifier", "non défensif"]


class TemplateResponseDraftProvider(ResponseDraftProvider):
    """
    Fournisseur contextuel sans clé API.

    Contrairement à l'ancien gabarit fondé uniquement sur la sévérité, il
    exécute d'abord un agent de décision explicable : répondre, surveiller,
    préparer un communiqué, escalader ou ne pas répondre.
    """

    def draft(
        self,
        organization_name: str,
        alert_reason: str,
        mention_text: str,
        severity: str,
        context: dict[str, Any] | None = None,
    ) -> ResponseDraftResult:
        resolved_context = dict(context or {})
        resolved_context.setdefault("alert_reason", alert_reason)
        resolved_context.setdefault("mention_text", mention_text)
        resolved_context.setdefault("severity", severity)

        decision = decide_response_action(resolved_context)

        if decision.action == "public_reply":
            fr, ar, tone = _build_public_reply(organization_name, decision)
        elif decision.action in {"official_statement", "internal_escalation"}:
            fr, ar, tone = _build_official_statement(organization_name, decision)
        elif decision.action == "no_reply":
            fr = "Aucune réponse publique n'est recommandée pour ce contenu."
            ar = "لا يُنصح بأي رد علني على هذا المحتوى."
            tone = ["aucune réponse"]
        else:
            fr, ar, tone = _build_monitoring_note(organization_name, decision)

        internal_note = decision.rationale
        if decision.action == "internal_escalation":
            internal_note += " Transmettre la source à la Direction Communication et, si nécessaire, au service juridique avant toute publication."
        elif decision.action == "official_statement":
            internal_note += " Utiliser ce texte comme projet de communiqué, uniquement après validation humaine."
        elif decision.action == "monitor":
            internal_note += " Surveiller l'évolution et répondre seulement si une demande directe ou des faits vérifiés apparaissent."

        details = {
            **decision.to_dict(),
            "severity": severity,
            "internal_note": internal_note,
            "source_context": {
                key: resolved_context.get(key)
                for key in (
                    "content_type", "source_type", "source_name", "title",
                    "author_name", "mention_url", "parent_title", "city",
                    "business_category", "engagement",
                )
            },
        }

        return ResponseDraftResult(
            content_by_language={"fr": fr, "ar": ar},
            tone=tone,
            model_provider="template",
            model_name="response-decision-template-v2",
            model_version="2.0",
            details=details,
        )
