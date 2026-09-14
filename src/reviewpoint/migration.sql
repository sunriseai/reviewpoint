-- Initial Reviewpoint service POC schema, 2026-09-13.
-- Standalone design artifact: not a migration for the existing prototype.
-- Multiple projects in one local POC database; not a tenant-isolation guarantee.
-- Actor IDs are canonical external issuer/subject keys; there is no local user store.
-- Enable foreign keys on EVERY connection. Service responsibilities are in sqlite-schema.md.
PRAGMA foreign_keys = ON;

-- Metadata only: repository references never authorize access or trigger fetching.
CREATE TABLE projects (
    project_id       TEXT PRIMARY KEY NOT NULL,
    project_key      TEXT NOT NULL UNIQUE CHECK (length(trim(project_key)) > 0),
    name             TEXT NOT NULL CHECK (length(trim(name)) > 0),
    metadata_json    TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)
                         AND json_type(metadata_json) = 'object'),
    created_by       TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
    created_at       TEXT NOT NULL
);

-- Current access projection. Changes and previous values are retained in events.
-- The API enforces permissions; these rows alone do not authorize SQL operations.
CREATE TABLE project_memberships (
    project_id       TEXT NOT NULL REFERENCES projects(project_id),
    actor_id         TEXT NOT NULL CHECK (length(trim(actor_id)) > 0),
    role             TEXT NOT NULL CHECK (role IN ('reviewer', 'approver', 'owner')),
    active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    version          INTEGER NOT NULL CHECK (version > 0),
    changed_by       TEXT NOT NULL CHECK (length(trim(changed_by)) > 0),
    changed_at       TEXT NOT NULL,
    PRIMARY KEY (project_id, actor_id)
);

-- Only published profiles are persisted here; editing drafts can remain client state.
CREATE TABLE profile_versions (
    project_id       TEXT NOT NULL REFERENCES projects(project_id),
    profile_id       TEXT NOT NULL,
    version          INTEGER NOT NULL CHECK (version > 0),
    name             TEXT NOT NULL CHECK (length(trim(name)) > 0),
    owner_id         TEXT NOT NULL,
    published_by     TEXT NOT NULL,
    published_at     TEXT NOT NULL,
    definition_json  TEXT NOT NULL CHECK (json_valid(definition_json)
                         AND json_type(definition_json) = 'object'),
    content_hash     TEXT NOT NULL,
    PRIMARY KEY (project_id, profile_id, version)
);

-- A case is one host work item at one named commitment point.
CREATE TABLE cases (
    case_id          TEXT PRIMARY KEY NOT NULL,
    project_id       TEXT NOT NULL REFERENCES projects(project_id),
    host_id          TEXT NOT NULL,
    workflow_id      TEXT NOT NULL,
    external_case_id TEXT NOT NULL,
    checkpoint_key   TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE (project_id, host_id, workflow_id, external_case_id, checkpoint_key),
    UNIQUE (project_id, case_id)
);

-- Changes to work, action, context or evidence require a new revision.
CREATE TABLE submissions (
    submission_id    TEXT PRIMARY KEY NOT NULL,
    project_id       TEXT NOT NULL,
    case_id          TEXT NOT NULL,
    revision         INTEGER NOT NULL CHECK (revision > 0),
    host_revision    TEXT NOT NULL,
    work_type        TEXT NOT NULL,
    summary          TEXT NOT NULL,
    action_type      TEXT NOT NULL,
    action_json      TEXT NOT NULL CHECK (json_valid(action_json)
                         AND json_type(action_json) = 'object'),
    work_json        TEXT NOT NULL CHECK (json_valid(work_json)
                         AND json_type(work_json) = 'object'),
    context_json     TEXT NOT NULL CHECK (json_valid(context_json)
                         AND json_type(context_json) = 'object'),
    evidence_json    TEXT NOT NULL CHECK (json_valid(evidence_json)
                         AND json_type(evidence_json) = 'array'),
    content_hash     TEXT NOT NULL,
    submitted_by     TEXT NOT NULL,
    received_at      TEXT NOT NULL,
    FOREIGN KEY (project_id, case_id) REFERENCES cases(project_id, case_id),
    UNIQUE (case_id, revision),
    UNIQUE (case_id, host_revision),
    UNIQUE (project_id, case_id, submission_id)
);

-- Reserve an assessment before starting evaluation. A pending/failed newer
-- assessment must not expose an older Yes as the current decision.
CREATE TABLE assessments (
    assessment_seq   INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id    TEXT NOT NULL UNIQUE,
    project_id       TEXT NOT NULL,
    case_id          TEXT NOT NULL,
    submission_id    TEXT NOT NULL,
    profile_id       TEXT NOT NULL,
    profile_version  INTEGER NOT NULL,
    request_key      TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    evaluator_version TEXT NOT NULL,
    evaluation_time  TEXT NOT NULL,
    requested_at     TEXT NOT NULL,
    finished_at      TEXT,
    recommendation  TEXT CHECK (recommendation IN ('yes', 'no')),
    result_json      TEXT CHECK (result_json IS NULL OR
                         (json_valid(result_json) AND json_type(result_json) = 'object')),
    run_json         TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(run_json)
                         AND json_type(run_json) = 'object'),
    result_hash      TEXT,
    error_json       TEXT CHECK (error_json IS NULL OR
                         (json_valid(error_json) AND json_type(error_json) = 'object')),
    FOREIGN KEY (project_id, case_id, submission_id) REFERENCES submissions(project_id, case_id, submission_id),
    FOREIGN KEY (project_id, profile_id, profile_version) REFERENCES profile_versions(project_id, profile_id, version),
    UNIQUE (case_id, request_key),
    UNIQUE (project_id, case_id, assessment_id),
    UNIQUE (project_id, assessment_id),
    CHECK (
        (status = 'pending' AND finished_at IS NULL AND recommendation IS NULL
            AND result_json IS NULL AND result_hash IS NULL AND error_json IS NULL)
        OR (status = 'completed' AND finished_at IS NOT NULL AND recommendation IS NOT NULL
            AND result_json IS NOT NULL AND result_hash IS NOT NULL AND error_json IS NULL)
        OR (status = 'failed' AND finished_at IS NOT NULL AND recommendation IS NULL
            AND result_json IS NULL AND result_hash IS NULL AND error_json IS NOT NULL)
    )
);
CREATE INDEX assessments_by_submission ON assessments(submission_id, assessment_seq);

CREATE TABLE decisions (
    decision_seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id      TEXT NOT NULL UNIQUE,
    project_id       TEXT NOT NULL,
    case_id          TEXT NOT NULL,
    assessment_id    TEXT NOT NULL,
    request_key      TEXT NOT NULL,
    kind             TEXT NOT NULL DEFAULT 'decision' CHECK (kind IN ('decision', 'revocation')),
    answer           TEXT CHECK (answer IN ('yes', 'no')),
    rationale        TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    actor_id         TEXT NOT NULL CHECK (length(trim(actor_id)) > 0),
    authority_json   TEXT NOT NULL CHECK (json_valid(authority_json)
                         AND json_type(authority_json) = 'object'),
    conditions_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(conditions_json)
                         AND json_type(conditions_json) = 'array'),
    supersedes_decision_id TEXT,
    recorded_at      TEXT NOT NULL,
    valid_until      TEXT,
    content_hash     TEXT NOT NULL,
    FOREIGN KEY (project_id, case_id, assessment_id) REFERENCES assessments(project_id, case_id, assessment_id),
    FOREIGN KEY (project_id, case_id, supersedes_decision_id) REFERENCES decisions(project_id, case_id, decision_id),
    UNIQUE (project_id, case_id, decision_id),
    UNIQUE (project_id, decision_id),
    UNIQUE (case_id, request_key),
    UNIQUE (supersedes_decision_id),
    CHECK (supersedes_decision_id IS NULL OR supersedes_decision_id <> decision_id),
    CHECK ((kind = 'decision' AND answer IS NOT NULL)
        OR (kind = 'revocation' AND answer IS NULL AND supersedes_decision_id IS NOT NULL
            AND json_array_length(conditions_json) = 0 AND valid_until IS NULL))
);
CREATE INDEX decisions_by_assessment ON decisions(assessment_id, decision_seq);

-- Concerns and host reports are events, not independently editable approvals.
-- Profile events may omit case_id; case events must supply it (service validation).
CREATE TABLE events (
    event_seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         TEXT NOT NULL UNIQUE,
    project_id       TEXT NOT NULL REFERENCES projects(project_id),
    case_id          TEXT,
    profile_id       TEXT,
    profile_version  INTEGER,
    assessment_id    TEXT,
    decision_id      TEXT,
    related_event_id TEXT,
    source_id        TEXT NOT NULL,
    source_event_key TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    actor_id         TEXT NOT NULL,
    recorded_at      TEXT NOT NULL,
    occurred_at      TEXT,
    payload_json     TEXT NOT NULL CHECK (json_valid(payload_json)
                         AND json_type(payload_json) = 'object'),
    FOREIGN KEY (project_id, profile_id, profile_version) REFERENCES profile_versions(project_id, profile_id, version),
    FOREIGN KEY (project_id, case_id) REFERENCES cases(project_id, case_id),
    FOREIGN KEY (project_id, assessment_id) REFERENCES assessments(project_id, assessment_id),
    FOREIGN KEY (project_id, decision_id) REFERENCES decisions(project_id, decision_id),
    FOREIGN KEY (project_id, related_event_id) REFERENCES events(project_id, event_id),
    UNIQUE (project_id, event_id),
    UNIQUE (project_id, source_id, source_event_key),
    CHECK ((profile_id IS NULL AND profile_version IS NULL)
        OR (profile_id IS NOT NULL AND profile_version IS NOT NULL))
);
CREATE INDEX events_by_case ON events(case_id, event_seq);
CREATE INDEX events_by_profile ON events(project_id, profile_id, profile_version, event_seq);
CREATE INDEX events_by_project ON events(project_id, event_seq);

-- Current means latest submission, then latest REQUESTED evaluation, then latest
-- decision on that evaluation. It does not mean authorized to execute: the API
-- still checks expiry, authority, conditions and the host's current work revision.
-- A revocation remains the latest record with a NULL answer; never fall back to Yes.
CREATE VIEW current_case_review AS
SELECT c.project_id, c.case_id, c.host_id, c.workflow_id, c.external_case_id, c.checkpoint_key,
       s.submission_id, s.revision, s.host_revision, s.content_hash AS submission_hash,
       s.action_type, a.assessment_id, a.status AS evaluation_status,
       a.profile_id, a.profile_version, a.recommendation,
       d.decision_id, d.kind AS decision_kind, d.answer, d.valid_until
FROM cases c
LEFT JOIN submissions s ON s.case_id = c.case_id AND s.revision = (
    SELECT MAX(s2.revision) FROM submissions s2 WHERE s2.case_id = c.case_id
)
LEFT JOIN assessments a ON a.submission_id = s.submission_id AND a.assessment_seq = (
    SELECT MAX(a2.assessment_seq) FROM assessments a2 WHERE a2.submission_id = s.submission_id
)
LEFT JOIN decisions d ON a.status = 'completed' AND d.assessment_id = a.assessment_id
    AND d.decision_seq = (
        SELECT MAX(d2.decision_seq) FROM decisions d2 WHERE d2.assessment_id = a.assessment_id
    )
    AND NOT EXISTS (SELECT 1 FROM decisions d3 WHERE d3.supersedes_decision_id = d.decision_id);
