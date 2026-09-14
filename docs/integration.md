# Integrating a host application

Use the service as a decision component. The core API has no dependency on the example host or its work fields. [Generated OpenAPI](../schemas/openapi.json) and per-record JSON schemas describe the public contract; `/docs` also exposes the API locally.

## Exchange

All resource paths below are under `/api/v1/projects/{project}`. Every mutation requires a bearer identity and `Idempotency-Key`. Keep the same key and body when retrying an uncertain request; a different body conflicts.

1. `POST /submissions`: supply a stable host/workflow/case/checkpoint reference, host revision, work, context, evidence and exact proposed action. Set `expected_submission_id` to the prior submission or null for a new case.
2. `POST /cases/{case}/assessments`: send the new submission ID, an exact profile reference and the current review token. Poll the returned status URL.
3. `GET /cases/{case}/review`: retrieve state, recommendation, findings, questions, limits, allowed actions, concerns and evidence location.
4. An authenticated human calls `POST /cases/{case}/decisions` with an explicit answer, rationale, assessment ID and current review token. A host integration credential cannot make this decision.
5. Before acting, the host reads the review again, compares the work revision and the entire action including target/parameters, and enforces its own controls and any decision conditions.
6. `POST /cases/{case}/host-reports`: report acknowledgement, execution or an outcome separately. A report does not create or change authorization.

See the executable [example client](../examples/work_review/client.py), sample [submission](../examples/work_review/submission.json) and [profile](../examples/work_review/profile.json). The client can inspect, revise or simulate a handoff; it never records a human answer.

## Identity and project access

The local adapter maps hashed bearer credentials to trusted `Principal` values. Production integrations must replace this adapter with verified identity from an external provider; arbitrary request-supplied user IDs are not authentication. Project detail returns `actor_id` for the authenticated caller so newly created profiles can attribute ownership without guessing from membership lists.

| Actor | Authority |
| --- | --- |
| Reviewer | Read evidence and raise/respond to concerns |
| Approver | Also evaluate undecided work, decide Yes/No and resolve case concerns |
| Owner | Also publish profiles, administer project access, replace/revoke decisions and resolve profile concerns |
| Integration | Explicit project/host/workflow-scoped read, submit, evaluate and report grants; no human decisions |

Membership lists and membership creation/change history are owner-only. Reviewer, approver and integration event feeds omit administrative membership events, including their reasons; normal actor attribution in review history remains visible. Event filtering happens before pagination and `upper_sequence` calculation. Cursors bind the query, caller and effective visibility; restart pagination when permissions or integration scope change.

External user records are not stored here. Historical attribution survives membership changes. Deactivated membership blocks new access but does not retroactively revoke decisions. Only an owner may reevaluate a submission once it has a decision. Project bootstrap is local; there is no public project-creation endpoint or full user-management system.

## Reuse the UI

The React [review card](../frontend/src/ReviewCard.jsx) accepts display props and callbacks; it has no API calls. [presentation.js](../frontend/src/presentation.js) maps retained records into those props. Consequences and priority come from the bound profile; recommendation prose comes directly from the API. Button availability combines API permissions with the compact form's inability to collect exceptions. Availability help is UI fallback text because the API does not supply per-action denial reasons.

The reference React application calls the core API for guidelines and decisions. The optional `/example-host` routes are installed only by `reviewpoint demo`: they demonstrate a host, authenticate a human operator, then call the core HTTP API with a private integration identity. They are not part of the core service contract. The bridge's field catalog powers the guided editor. `reviewpoint serve` omits these routes; API-managed profiles remain inspectable.

## Enforcement limits

The example only simulates execution against a synthetic target. Its execution report uses an action ID prefixed `simulation:`; this is not evidence of a real external action. The service does not provide an execution lease or a transaction spanning host execution and revocation. A read can race a subsequent change. Real hosts need their own idempotent execution boundary and must not fall back to stale approval when current authorization cannot be retrieved.

Retained inputs are bounded text/JSON, not original binary artifacts or independently authenticated truth. URLs are not fetched. Multi-project isolation is tested, but shared production authentication, tenancy administration, connectors and operational guarantees require further implementation.
