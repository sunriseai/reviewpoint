import React from "react";
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  ProfileEditor,
  canEditRequirement,
  validateDraft,
} from "./Guidelines.jsx";
import { presentReview } from "./presentation.js";
afterEach(cleanup);
const fields = [
  { pointer: "/work/summary", label: "Summary" },
  { pointer: "/work/a", label: "Expected" },
  { pointer: "/work/b", label: "Supplied" },
];
const definition = {
  scope: { work_types: ["work_item"], action_types: ["release_work"] },
  risks: [
    {
      id: "a",
      title: "Rework",
      consequence: "Work needs correction",
      applies_to: "proceed",
    },
    {
      id: "b",
      title: "Delay",
      consequence: "The next step waits",
      applies_to: "hold",
    },
  ],
  requirements: [
    {
      id: "r",
      description: "Summary exists",
      risk_ids: ["a"],
      check: {
        id: "required_values",
        parameters: { pointers: ["/work/summary"] },
      },
    },
  ],
  review_rules: { decision_max_age_seconds: 3600 },
};
const profile = { name: "Guidelines", owner_id: "owner", definition };
test("publishes edits and ordering without mutating the source profile or dropping API-managed checks", async () => {
  const user = userEvent.setup(),
    save = vi.fn();
  const managed = {
    id: "semantic",
    description: "Source supports the intended use",
    risk_ids: ["a"],
    check: {
      id: "semantic_review",
      parameters: { question: "Does the source support the intended use?" },
    },
    applicability: { kind: "always" },
  };
  const input = {
    ...profile,
    definition: {
      ...definition,
      requirements: [...definition.requirements, managed],
    },
  };
  render(<ProfileEditor profile={input} fields={fields} onSave={save} />);
  expect(
    screen.getAllByRole("button", { name: "Remove risk" })[0].disabled,
  ).toBe(true);
  expect(screen.getByText(/API-managed requirement/)).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Move Delay up" }));
  const first = screen.getByRole("region", { name: "Risk 1" });
  await user.selectOptions(within(first).getByLabelText("Applies to"), "both");
  await user.type(
    screen.getByLabelText("Reason for publishing"),
    "Delay matters to the next step",
  );
  await user.click(screen.getByRole("button", { name: "Publish version" }));
  const draft = save.mock.calls[0][0];
  expect(draft.definition.risks[0]).toMatchObject({
    id: "b",
    applies_to: "both",
  });
  expect(draft.definition.requirements[1]).toEqual(managed);
  expect(draft.definition.review_rules).toEqual(definition.review_rules);
  expect(input.definition.risks[0].id).toBe("a");
});
test("creates a profile with a required value and rejects an unassociated requirement", async () => {
  const user = userEvent.setup(),
    save = vi.fn();
  render(<ProfileEditor fields={fields} ownerId="owner" onSave={save} />);
  await user.click(screen.getByRole("button", { name: "Add requirement" }));
  await user.type(
    screen.getByLabelText("Reason for publishing"),
    "First guidelines",
  );
  await user.click(screen.getByLabelText("Incomplete work"));
  await user.click(screen.getByRole("button", { name: "Publish version" }));
  expect(screen.getByRole("alert").textContent).toContain("existing risk");
  expect(save).not.toHaveBeenCalled();
  await user.click(screen.getByLabelText("Incomplete work"));
  await user.click(screen.getByRole("button", { name: "Publish version" }));
  expect(save.mock.calls[0][0].owner_id).toBe("owner");
});
test("mapping follows explicit applies_to rather than names; unknown field checks stay API-managed", () => {
  const review = {
    allowed_actions: [],
    evaluation_status: "completed",
    recommendation: { answer: "no", reason: "Missing support" },
  };
  const risks = [
    { id: "delay", consequence: "Any label", applies_to: "proceed" },
    { id: "other", consequence: "Shared consequence", applies_to: "both" },
  ];
  const result = presentReview(review, {}, { definition: { risks } });
  expect(result.proceedRisks.map((r) => r.id)).toEqual(["delay", "other"]);
  expect(result.holdRisks.map((r) => r.id)).toEqual(["other"]);
  expect(
    canEditRequirement(
      {
        check: {
          id: "equal_values",
          parameters: { left: "/unknown", right: "/work/a" },
        },
      },
      fields,
    ),
  ).toBe(false);
});

test("a newly selected comparison cannot silently publish a field compared to itself", () => {
  const draft = {
    name: "Guidelines",
    reason: "Revise checks",
    definition: {
      ...definition,
      requirements: [
        {
          id: "r",
          description: "Compare",
          risk_ids: ["a"],
          check: {
            id: "equal_values",
            parameters: { left: "/work/a", right: "/work/a" },
          },
        },
      ],
    },
  };
  expect(validateDraft(draft)).toContain("different fields");
});
