"""Service contracts. External identities and domain data are distinct from authority."""

import math
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
ID = Annotated[str, StringConstraints(min_length=1, max_length=256)]
Role = Literal["reviewer", "approver", "owner"]
Status = Literal["met", "unmet", "unknown", "not_applicable"]
JSON = dict[str, Any]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def finite_json(cls, value: Any) -> Any:
        pending = [value]
        while pending:
            item = pending.pop()
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("JSON numbers must be finite")
            if isinstance(item, dict):
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        return value


class ProjectEdit(Model):
    expected_version: int = Field(ge=1)
    reason: Text
    name: Text | None = None
    metadata: JSON | None = None

    @model_validator(mode="after")
    def validate_host_checks(self) -> Self:
        if self.metadata is not None and "host_checks" in self.metadata:
            checks = self.metadata["host_checks"]
            if not isinstance(checks, dict) or any(
                not isinstance(host, str)
                or not host
                or not isinstance(names, list)
                or any(not isinstance(name, str) or not name for name in names)
                for host, names in checks.items()
            ):
                raise ValueError("host_checks must map host IDs to lists of named checks")
        return self


class MembershipEdit(Model):
    actor_id: ID
    role: Role
    active: bool
    expected_version: int = Field(ge=0)
    reason: Text


class Method(Model):
    id: Literal[
        "required_values",
        "equal_values",
        "reconcile_records",
        "evidence_binding",
        "semantic_review",
    ]
    version: Literal[1] = 1
    parameters: JSON = Field(default_factory=dict)


class Applicability(Model):
    kind: Literal["always", "equals"] = "always"
    pointer: str | None = None
    value: Any = None


class ExceptionRule(Model):
    allowed_statuses: list[Literal["unmet", "unknown"]] = Field(default_factory=list)
    role: Literal["owner"] = "owner"


class Risk(Model):
    applies_to: Literal["proceed", "hold", "both"]
    id: ID
    title: Text
    consequence: Text


class Requirement(Model):
    id: ID
    description: Text
    risk_ids: list[ID] = Field(min_length=1)
    applicability: Applicability = Field(default_factory=Applicability)
    check: Method
    exception: ExceptionRule = Field(default_factory=ExceptionRule)


class Scope(Model):
    work_types: list[ID] = Field(min_length=1)
    action_types: list[ID] = Field(min_length=1)


class ReviewRules(Model):
    evidence_max_age_seconds: int = Field(default=86400, ge=1, le=31536000)
    decision_max_age_seconds: int = Field(default=3600, ge=1, le=31536000)
    permitted_condition_types: list[Literal["host_check"]] = Field(default_factory=list)


class Definition(Model):
    scope: Scope
    risks: list[Risk] = Field(min_length=1, max_length=30)
    requirements: list[Requirement] = Field(min_length=1, max_length=100)
    review_rules: ReviewRules = Field(default_factory=ReviewRules)

    @model_validator(mode="after")
    def references(self) -> Self:
        risks = {r.id for r in self.risks}
        if len(risks) != len(self.risks) or len({r.id for r in self.requirements}) != len(
            self.requirements
        ):
            raise ValueError("duplicate risk or requirement IDs")
        if any(not set(r.risk_ids) <= risks for r in self.requirements):
            raise ValueError("unknown risk reference")
        return self


class PublishProfile(Model):
    name: Text
    owner_id: ID
    definition: Definition
    reason: Text


class PublishVersion(PublishProfile):
    expected_latest_version: int = Field(ge=1)


class CaseRef(Model):
    host_id: ID
    workflow_id: ID
    external_case_id: ID
    checkpoint_key: ID


class Action(Model):
    type: ID
    label: Text
    target: ID
    parameters: JSON = Field(default_factory=dict)


class Evidence(Model):
    id: ID
    title: Text
    media_type: Literal["text/plain", "text/markdown", "application/json"] = "text/plain"
    source_uri: Text
    captured_at: AwareDatetime
    content: str = Field(min_length=1, max_length=100000)
    content_hash: str | None = None
    original_artifact_hash: str | None = None
    scope: Text = "Selected source excerpt; not a complete original artifact"


class Submission(Model):
    case_ref: CaseRef
    expected_submission_id: ID | None
    host_revision: ID
    work_type: ID
    summary: Text
    proposed_action: Action
    work: JSON
    context: JSON = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def evidence_limits(self) -> Self:
        if len({e.id for e in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate evidence IDs")
        if sum(len(e.content.encode()) for e in self.evidence) > 1048576:
            raise ValueError("evidence exceeds 1 MiB")
        return self


class ProfileRef(Model):
    id: ID
    version: int = Field(ge=1)


class AssessmentRequest(Model):
    submission_id: ID
    profile_ref: ProfileRef
    expected_review_token: ID


class ExceptionRequest(Model):
    requirement_id: ID
    rationale: Text


class Condition(Model):
    id: ID
    type: Literal["host_check"]
    description: Text
    parameters: dict[Literal["check_id"], ID]


class DecisionRequest(Model):
    assessment_id: ID
    expected_review_token: ID
    supersedes_decision_id: ID | None = None
    answer: Literal["yes", "no"]
    rationale: Text
    exceptions: list[ExceptionRequest] = Field(default_factory=list)
    conditions: list[Condition] = Field(default_factory=list)
    valid_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def distinct(self) -> Self:
        if self.answer == "no" and (self.exceptions or self.conditions or self.valid_until):
            raise ValueError("No cannot carry exceptions, conditions or expiry")
        if len({e.requirement_id for e in self.exceptions}) != len(self.exceptions):
            raise ValueError("duplicate exceptions")
        if len({c.id for c in self.conditions}) != len(self.conditions):
            raise ValueError("duplicate conditions")
        return self


class Revocation(Model):
    expected_review_token: ID
    rationale: Text


class Concern(Model):
    case_id: ID | None = None
    assessment_id: ID | None = None
    finding_id: ID | None = None
    profile_ref: ProfileRef | None = None
    category: Literal["evidence", "interpretation", "profile", "other"]
    message: Text

    @model_validator(mode="after")
    def target(self) -> Self:
        if (self.case_id is None) == (self.profile_ref is None):
            raise ValueError("select exactly one case or profile")
        if self.assessment_id and not self.case_id or self.finding_id and not self.assessment_id:
            raise ValueError("finding requires assessment; assessment requires case")
        return self


class ConcernResponse(Model):
    expected_concern_version: int = Field(ge=1)
    message: Text
    resolve: bool = False
    corrective_submission_id: ID | None = None
    corrective_assessment_id: ID | None = None
    corrective_profile_ref: ProfileRef | None = None


class HostReport(Model):
    decision_id: ID
    type: Literal["acknowledged", "execution_reported", "outcome_reported"]
    occurred_at: AwareDatetime
    details: JSON
    corrects_event_id: ID | None = None


class Reference(Model):
    source: Literal["work", "context", "evidence"]
    pointer: str | None = None
    evidence_id: ID | None = None
    quote: str | None = None


class RequirementResult(Model):
    requirement_id: ID
    status: Status
    explanation: Text
    method: Method
    references: list[Reference]


class Finding(Model):
    id: ID
    statement: Text
    scope: Text
    risk_ids: list[ID]
    requirement_id: ID | None
    method: str
    references: list[Reference]
    interpretation: bool


class Question(Model):
    id: ID
    question: Text
    requirement_id: ID
    finding_id: ID


class Recommendation(Model):
    answer: Literal["yes", "no"]
    reason: Text


class EvaluationResult(Model):
    recommendation: Recommendation
    requirement_results: list[RequirementResult]
    findings: list[Finding]
    questions: list[Question]
    limits: list[str]
    valid_until: datetime


class SemanticAnswer(Model):
    status: Literal["met", "unmet", "unknown"]
    explanation: Text
    references: list[Reference]
    limits: list[Text]


class ProjectRecord(Model):
    project_id: str
    project_key: str
    name: str
    metadata: JSON
    created_by: str
    created_at: AwareDatetime


class ProjectSummary(ProjectRecord):
    role: str


class ProjectDetail(ProjectSummary):
    actor_id: str
    version: int
    capabilities: list[str]
    authentication: str
    limits: dict[str, int]


class ProjectChanged(ProjectRecord):
    version: int


class MembershipRecord(Model):
    project_id: str
    actor_id: str
    role: Role
    active: int
    version: int
    changed_by: str
    changed_at: AwareDatetime


class ProfileRecord(Model):
    project_id: str
    profile_id: str
    version: int
    name: str
    owner_id: str
    published_by: str
    published_at: AwareDatetime
    definition: Definition
    content_hash: str


class CaseRecord(Model):
    case_id: str
    project_id: str
    host_id: str
    workflow_id: str
    external_case_id: str
    checkpoint_key: str
    created_at: AwareDatetime


class CaseSummary(CaseRecord):
    state: str
    summary: str | None


class SubmissionRecord(Model):
    submission_id: str
    project_id: str
    case_id: str
    revision: int
    host_revision: str
    work_type: str
    summary: str
    action_type: str
    action: Action
    work: JSON
    context: JSON
    evidence: list[Evidence]
    content_hash: str
    submitted_by: str
    received_at: AwareDatetime


class SubmissionReceipt(Model):
    case_id: str
    submission_id: str
    revision: int
    host_revision: str
    content_hash: str
    received_at: AwareDatetime
    review_token: str


class AssessmentReceipt(Model):
    assessment_id: str
    status: Literal["pending"]
    status_url: str


class AssessmentRecord(Model):
    assessment_seq: int
    assessment_id: str
    project_id: str
    case_id: str
    submission_id: str
    profile_id: str
    profile_version: int
    request_key: str
    status: Literal["pending", "completed", "failed"]
    evaluator_version: str
    evaluation_time: AwareDatetime
    requested_at: AwareDatetime
    finished_at: AwareDatetime | None
    recommendation: Literal["yes", "no"] | None
    result: EvaluationResult | None
    run: JSON
    result_hash: str | None
    error: JSON | None


class DecisionRecord(Model):
    decision_seq: int
    decision_id: str
    project_id: str
    case_id: str
    assessment_id: str
    request_key: str
    kind: Literal["decision", "revocation"]
    answer: Literal["yes", "no"] | None
    rationale: str
    actor_id: str
    authority: JSON
    conditions: list[Condition]
    supersedes_decision_id: str | None
    recorded_at: AwareDatetime
    valid_until: AwareDatetime | None
    content_hash: str


class EventRecord(Model):
    event_seq: int
    event_id: str
    project_id: str
    case_id: str | None
    profile_id: str | None
    profile_version: int | None
    assessment_id: str | None
    decision_id: str | None
    related_event_id: str | None
    source_id: str
    source_event_key: str
    event_type: str
    actor_id: str
    recorded_at: AwareDatetime
    occurred_at: AwareDatetime | None
    payload: JSON


class ConcernRecord(EventRecord):
    concern_id: str
    version: int
    resolved: bool
    responses: list[EventRecord]


class ConcernReceipt(Model):
    concern_id: str
    version: int
    resolved: bool


class ResponseReceipt(Model):
    concern_id: str
    event_id: str
    version: int


class Review(Model):
    case_id: str
    project_id: str
    state: Literal[
        "awaiting_evaluation",
        "evaluating",
        "evaluation_failed",
        "awaiting_decision",
        "revoked",
        "expired",
        "declined",
        "approved_with_conditions",
        "approved",
    ]
    observed_at: AwareDatetime
    review_token: str
    submission_id: str | None
    host_revision: str | None
    submission_hash: str | None
    proposed_action: Action | None
    summary: str | None
    assessment_id: str | None
    evaluation_status: Literal["pending", "completed", "failed"] | None
    profile_ref: ProfileRef | None
    recommendation: Recommendation | None
    result: EvaluationResult | None
    error: JSON | None
    current_decision: DecisionRecord | None
    concerns: list[ConcernRecord]
    allowed_actions: list[
        Literal["raise_concern", "evaluate", "record_no", "record_yes", "revoke_decision"]
    ]
    evidence_url: str | None


class Page[T](Model):
    items: list[T]
    next_cursor: str | None


class EventPage(Page[EventRecord]):
    upper_sequence: int


class ErrorDetail(Model):
    code: str
    message: str
    request_id: str


class ErrorResponse(Model):
    error: ErrorDetail
