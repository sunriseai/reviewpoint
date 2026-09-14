"""A host uses the public API. Human decisions are deliberately absent from this client."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

import httpx

from reviewpoint.demo import PROJECT, submission
from reviewpoint.storage import now


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inspect", "revise", "handoff"])
    parser.add_argument("--workspace", type=Path, default=Path(".workspace"))
    parser.add_argument("--url", default="http://127.0.0.1:8767")
    parser.add_argument("--supplied-items", type=int, default=4)
    args = parser.parse_args()
    credential = json.loads((args.workspace / "demo-credentials.json").read_text())["host"]
    with httpx.Client(
        base_url=args.url, headers={"Authorization": "Bearer " + credential}, timeout=30
    ) as client:

        def call(method, path, body=None):
            # This simple client stops on uncertain failures. A production host retains
            # this key AND body durably to retry the same operation without duplication.
            response = client.request(
                method, path, json=body, headers={"Idempotency-Key": uuid4().hex}
            )
            response.raise_for_status()
            return response.json()

        base = f"/api/v1/projects/{PROJECT}"
        case = next(
            c for c in call("GET", base + "/cases")["items"] if c["external_case_id"] == "WORK-001"
        )
        path = base + "/cases/" + case["case_id"]
        review = call("GET", path + "/review")
        frozen = call("GET", review["evidence_url"])
        if args.command == "inspect":
            print(json.dumps(review, indent=2))
        elif args.command == "revise":
            revised = submission(
                {**frozen["work"], "supplied_items": args.supplied_items},
                previous=frozen["submission_id"],
                revision=frozen["revision"] + 1,
            )
            receipt = call("POST", base + "/submissions", revised.model_dump(mode="json"))
            print(json.dumps(receipt, indent=2))
            print("Select guidelines and request evaluation in the UI. No human decision was made.")
        else:
            if (
                review["state"] != "approved"
                or review["proposed_action"] != frozen["action"]
                or review["host_revision"] != frozen["host_revision"]
            ):
                raise SystemExit("No current matching unconditional approval; no action performed.")
            decision = review["current_decision"]["decision_id"]
            call(
                "POST",
                path + "/host-reports",
                {
                    "decision_id": decision,
                    "type": "acknowledged",
                    "occurred_at": now(),
                    "details": {"message": "Decision retrieved for a simulated handoff only"},
                },
            )
            report = call(
                "POST",
                path + "/host-reports",
                {
                    "decision_id": decision,
                    "type": "execution_reported",
                    "occurred_at": now(),
                    "details": {
                        "status": "succeeded",
                        "host_action_id": "simulation:" + decision,
                        "host_revision": frozen["host_revision"],
                        "proposed_action": frozen["action"],
                    },
                },
            )
            print(json.dumps(report, indent=2))
            print("Simulated handoff reported. No real action performed.")


if __name__ == "__main__":
    run()
