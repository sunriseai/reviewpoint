"""Synthetic host inputs; evaluator results are computed, not supplied as fixtures."""

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from reviewpoint.identity import DemoIdentity, Principal
from reviewpoint.models import PublishProfile, Submission
from reviewpoint.service import Service
from reviewpoint.storage import Store, dumps, event, insert, now

DOMAINS = {
    "work": (
        "order",
        "prepare_fulfillment_handoff",
        "Incorrect fulfillment",
        "Every declared item is accounted for",
        "equal_values",
        {"left": "/work/declared", "right": "/work/supported"},
    ),
    "reconciliation": (
        "reconciliation",
        "accept_reconciliation",
        "Incorrect accounting",
        "Identity, account and amount agree for each source row",
        "reconcile_records",
        {"pointer": "/work/rows", "currency": "USD", "tolerance": "0.00"},
    ),
    "mapping": (
        "account_data",
        "generate_paperwork",
        "Incorrect paperwork",
        "Source and target meanings match",
        "equal_values",
        {"left": "/work/source_meaning", "right": "/work/target_meaning"},
    ),
    "release": (
        "remediation",
        "promote_candidate",
        "Security exposure",
        "Scan identifies the exact candidate image",
        "evidence_binding",
        {
            "evidence_id": "scan",
            "work_pointer": "/work/image_digest",
            "evidence_pointer": "/image_digest",
        },
    ),
}


def profile(domain: str, owner: str, *, semantic: bool = False) -> PublishProfile:
    work, action, risk, requirement, method, params = DOMAINS[domain]
    requirements = [
        {
            "id": "primary",
            "description": requirement,
            "risk_ids": ["correctness"],
            "check": {"id": method, "parameters": params},
        }
    ]
    if domain == "mapping":
        requirements.append(
            {
                "id": "applicable_data",
                "description": "A corporate account has its registration number",
                "risk_ids": ["correctness"],
                "applicability": {
                    "kind": "equals",
                    "pointer": "/work/account_type",
                    "value": "corporate",
                },
                "check": {
                    "id": "required_values",
                    "parameters": {"pointers": ["/work/registration_number"]},
                },
            }
        )
    if domain == "release":
        requirements.append(
            {
                "id": "scan_result",
                "description": "Supplied scan reports zero unresolved high findings",
                "risk_ids": ["correctness"],
                "check": {
                    "id": "equal_values",
                    "parameters": {
                        "left": "/work/unresolved_high",
                        "right": "/context/required_high_count",
                    },
                },
            }
        )
    if semantic:
        requirements.append(
            {
                "id": "meaning",
                "description": "The supplied evidence supports the intended use",
                "risk_ids": ["correctness"],
                "check": {
                    "id": "semantic_review",
                    "parameters": {
                        "question": (
                            "Does the supplied source support the proposed action's stated "
                            "meaning? Identify an unsupported mapping or missing item; do not "
                            "infer executed scans or tests."
                        )
                    },
                },
            }
        )
    return PublishProfile.model_validate(
        {
            "name": f"{domain.title()} illustrative review"
            + (" with interpretation" if semantic else ""),
            "owner_id": owner,
            "reason": "Synthetic demo profile; business-owner approval pending",
            "definition": {
                "scope": {"work_types": [work], "action_types": [action]},
                "risks": [
                    {
                        "id": "correctness",
                        "title": risk,
                        "consequence": risk,
                        "applies_to": "proceed",
                    },
                    {
                        "id": "delay",
                        "applies_to": "hold",
                        "title": "Slower processing",
                        "consequence": "Unnecessary review delays the host workflow",
                    },
                ],
                "requirements": requirements,
            },
        }
    )


def submission(
    domain: str, supported: bool = True, *, external_id: str | None = None
) -> Submission:
    work_type, action, *_ = DOMAINS[domain]
    work: dict[str, Any]
    if domain == "work":
        work = {"declared": 4, "supported": 4 if supported else 3, "phone": None}
    elif domain == "reconciliation":
        work = {
            "rows": [
                {
                    "id": "row-1",
                    "expected_identity": "guest-A",
                    "actual_identity": "guest-A" if supported else "guest-B",
                    "expected_account": "receivable",
                    "actual_account": "receivable",
                    "expected_amount": "-12.50",
                    "actual_amount": "-12.50",
                    "currency": "USD",
                }
            ]
        }
    elif domain == "mapping":
        work = {
            "source_meaning": "country_of_issue" if supported else "place_of_birth",
            "target_meaning": "country_of_issue",
            "account_type": "individual",
        }
    else:
        work = {"image_digest": "sha256:candidate-demo", "unresolved_high": 0}
    content = (
        dumps(
            {
                "image_digest": "sha256:candidate-demo" if supported else "sha256:older-demo",
                "unresolved_high": 0,
            }
        )
        if domain == "release"
        else dumps(work)
    )
    return Submission.model_validate(
        {
            "case_ref": {
                "host_id": domain,
                "workflow_id": "demo",
                "external_case_id": external_id or ("supported" if supported else "hold"),
                "checkpoint_key": action,
            },
            "expected_submission_id": None,
            "host_revision": "revision-1",
            "work_type": work_type,
            "summary": f"Synthetic {domain} {'supported' if supported else 'hold'} example",
            "proposed_action": {
                "type": action,
                "label": f"Proceed with {action.replace('_', ' ')}?",
                "target": "demo-only",
                "parameters": {},
            },
            "work": work,
            "context": {
                "required_high_count": 0,
                "policy_status": "Illustrative; owner review pending",
            },
            "evidence": [
                {
                    "id": "scan" if domain == "release" else "source",
                    "title": "Synthetic source",
                    "media_type": "application/json",
                    "source_uri": "demo:" + domain,
                    "captured_at": now(),
                    "content": content,
                }
            ],
        }
    )


def seed(path: Path) -> dict[str, Any]:
    """Create a fresh private demo workspace; never overwrite existing business data."""
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    store = Store(path / "reviewpoint.sqlite3")
    store.initialize()
    service = Service(store)
    people = {
        name: Principal("reviewpoint-local-demo", name)
        for name in ("owner", "approver", "reviewer")
    }
    people.update(
        {
            domain + "-host": Principal(
                "reviewpoint-local-demo",
                domain + "-host",
                "integration",
                {
                    domain: {
                        "capabilities": ["read", "submit", "evaluate", "report"],
                        "host_id": domain,
                        "workflow_ids": ["demo"],
                    }
                },
            )
            for domain in DOMAINS
        }
    )
    tokens = {name: secrets.token_urlsafe(32) for name in people}
    config: dict[str, Any] = {
        "authentication": "simulated_external_identity",
        "principals": {},
        "model": "gpt-5.6-luna",
        "openai": False,
    }
    for name, person in people.items():
        config["principals"][hashlib.sha256(tokens[name].encode()).hexdigest()] = {
            "issuer": person.issuer,
            "subject": person.subject,
            "kind": person.kind,
            "grants": person.grants,
        }
    profiles = {}
    with store.transaction(write=True) as c:
        for domain in DOMAINS:
            insert(
                c,
                "projects",
                project_id=domain,
                project_key=domain,
                name=domain.title(),
                metadata_json=dumps(
                    {
                        "description": "Synthetic demonstration; not owner-approved policy",
                        "repositories": [],
                        "host_checks": {domain: ["manual_handoff_confirmed"]},
                    }
                ),
                created_by=people["owner"].actor_id,
                created_at=now(),
            )
            event(c, domain, people["owner"].actor_id, "project.created", {"demo": True})
            for role in ("owner", "approver", "reviewer"):
                insert(
                    c,
                    "project_memberships",
                    project_id=domain,
                    actor_id=people[role].actor_id,
                    role=role,
                    active=1,
                    version=1,
                    changed_by=people["owner"].actor_id,
                    changed_at=now(),
                )
                event(
                    c,
                    domain,
                    people["owner"].actor_id,
                    "membership.created",
                    {"actor_id": people[role].actor_id, "role": role},
                )
    for domain in DOMAINS:
        profiles[domain] = service.publish(
            people["owner"], domain, "bootstrap", profile(domain, people["owner"].actor_id)
        )[1]["profile_id"]
    for filename, value in (
        ("config.json", config),
        ("demo-credentials.json", tokens),
        ("demo-profiles.json", profiles),
    ):
        file = path / filename
        file.write_text(dumps(value) + "\n")
        file.chmod(0o600)
    return {
        "workspace": str(path),
        "projects": list(DOMAINS),
        "credentials_file": str(path / "demo-credentials.json"),
    }


def load(path: Path, *, live: bool = False) -> tuple[Service, DemoIdentity]:
    from reviewpoint.openai_transport import OpenAITransport

    config = json.loads((path / "config.json").read_text())
    store = Store(path / "reviewpoint.sqlite3")
    store.initialize()
    identity = DemoIdentity(
        {key: Principal(**value) for key, value in config["principals"].items()}
    )
    return Service(
        store, OpenAITransport() if live else None, config.get("model", "gpt-5.6-luna")
    ), identity
