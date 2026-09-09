from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ReputationHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    reputation_score: float
    mention_count: int
    positive_rate: float | None
    negative_rate: float | None
    delta_previous_period: float | None


class BenchmarkEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: int
    organization_name: str
    organization_type: str
    period_start: date
    period_end: date
    reputation_score: float | None
    mention_count: int
    has_data: bool
    positive_rate: float | None
    negative_rate: float | None
    delta_previous_period: float | None
    dominant_topic: str | None
    confidence: dict = Field(default_factory=dict)


class PeriodOption(BaseModel):
    """Une période consultable dans le sélecteur du portail."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    period_type: str
    label: str
    has_snapshot: bool
    reputation_score: float | None
    mention_count: int
    open_alerts: int
    handled_alerts: int
    total_alerts: int
    is_latest: bool


class ReputationScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: int
    organization_name: str
    period_start: date
    period_end: date
    period_type: str
    reputation_score: float
    mention_count: int
    positive_count: int
    neutral_count: int
    negative_count: int
    positive_rate: float | None
    negative_rate: float | None
    delta_previous_period: float | None
    analyst_summary: str | None
    dominant_topic: str | None
    confidence: dict = Field(default_factory=dict)


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mention_id: int
    data_type: str = "real"
    organization_name: str
    alert_type: str
    severity: str
    reason: str
    status: str
    source_name: str | None
    content_type: str
    content_label: str
    author_name: str | None
    published_at: datetime | None
    collected_at: datetime
    parent_title: str | None
    parent_url: str | None
    engagement: dict
    mention_url: str | None
    mention_excerpt: str | None
    comment_triage: dict | None = None
    sentiment_label: str | None = None
    sentiment_source: str | None = None
    risk_categories: list[str] = Field(default_factory=list)
    assigned_to: str | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    is_handled: bool = False
    validated_by: str | None = None
    validated_at: datetime | None = None
    validation_note: str | None = None
    created_at: datetime
    grouped_count: int = 1
    grouped_alert_ids: list[int] = Field(default_factory=list)
    related_sources: list[dict] = Field(default_factory=list)
    facebook_capture: dict | None = None
    collection_provider: str | None = None
    # Ville concernee, deduite du texte, du titre ou de l'URL. `city_source`
    # dit lequel des trois a repondu, pour que l'utilisateur puisse verifier.
    city: str | None = None
    city_source: str | None = None
    city_source_label: str | None = None
    # Mot exact ayant declenche le rattachement : « ain sebaa » doit rester
    # verifiable, sinon rattacher un quartier a sa ville parait arbitraire.
    city_evidence: str | None = None
    cities: list[str] = Field(default_factory=list)


class ResponseDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_id: int
    content_by_language: dict
    tone: list[str]
    status: str
    generated_at: datetime
    action: str
    action_label: str
    category: str
    reply_eligible: bool
    requires_human_validation: bool
    internal_note: str | None
    rationale: str | None
    recommended_channel: str | None
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None


class AlertStatusUpdate(BaseModel):
    status: str = Field(pattern="^(open|acknowledged|resolved|ignored)$")
    # Trace de validation humaine : qui a cliqué sur « Valider » et pourquoi.
    # Les deux champs sont facultatifs pour rester compatible avec les appels
    # existants du portail et du workflow n8n.
    note: str | None = Field(default=None, max_length=1000)
    validated_by: str | None = Field(default=None, max_length=200)


class StrategicAngleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    title: str
    description: str
    rationale: str | None
    priority_score: float | None
    status: str
    target_platforms: list[str]
    generated_at: datetime


class RecentMentionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    summary: str | None
    source_name: str
    url: str | None
    published_at: datetime | None
    collected_at: datetime
    published_at_confidence: str = "unknown"
    published_at_source: str = "unknown"
    freshness: str = "unknown"
    category_label: str | None = None
    route: dict = Field(default_factory=dict)
    validation_status: str = "pending"
    topics: list[str]
    category: str | None
    relevance_score: float | None
    content_type: str
    business_insight: str | None
    duplicate_count: int = 1
    related_sources: list[dict] = Field(default_factory=list)
    geography: dict = Field(default_factory=dict)
    facebook_capture: dict | None = None


class GeneratedPostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    strategic_angle_id: int | None
    platform: str
    content_by_language: dict
    image_prompt: str | None
    tone: list[str]
    status: str
    display_order: int | None
    generated_at: datetime
    model_provider: str | None = None
    quality_checked: bool = False
    fallback_used: bool = False
    evidence: list[dict] = Field(default_factory=list)
    claim_status: str = "internal_validation_required"
    warnings: list[str] = Field(default_factory=list)
    model_name: str | None = None
    model_version: str | None = None
