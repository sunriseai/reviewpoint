import React from "react";
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReviewCard from "./ReviewCard.jsx";
import { presentReview } from "./presentation.js";

afterEach(cleanup);
const props = {
  systemId: "WORK-001",
  action: "Release this work to the next step.",
  headline: "One item is unaccounted for",
  bullets: ["4 declared; 3 accounted for."],
  proceedRisk: "Incomplete work",
  holdRisk: "Possible delay",
  recommendation: "no",
  explanation: "Account for the fourth item.",
  canHold: true,
};

test("recommendation is not a selected or saved decision; hold needs an explicit reason", async () => {
  const user = userEvent.setup();
  const save = vi.fn().mockResolvedValue(undefined);
  render(<ReviewCard {...props} onDecision={save} />);
  expect(screen.getByRole("button", { name: "Proceed" }).disabled).toBe(true);
  const hold = screen.getByRole("button", { name: "Hold / fix" });
  expect(hold.getAttribute("aria-pressed")).toBe("false");
  await user.click(hold);
  expect(
    screen
      .getByRole("textbox")
      .compareDocumentPosition(screen.getByText(props.explanation)) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox").value).toBe("");
  expect(screen.getByRole("button", { name: "Record hold" }).disabled).toBe(
    true,
  );
  await user.type(
    screen.getByRole("textbox"),
    "The fourth item needs confirmation.",
  );
  await user.click(screen.getByRole("button", { name: "Record hold" }));
  expect(save).toHaveBeenCalledWith({
    answer: "no",
    rationale: "The fourth item needs confirmation.",
  });
  expect(screen.getByRole("status").textContent).toContain(
    "Host action has not been confirmed",
  );
});

test("a failed write retains the reason, shows the error, and offers refresh", async () => {
  const user = userEvent.setup();
  const refresh = vi.fn();
  render(
    <ReviewCard
      {...props}
      onRefresh={refresh}
      onDecision={vi
        .fn()
        .mockRejectedValue(Error("Review changed. Refresh first."))}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Hold / fix" }));
  await user.type(screen.getByRole("textbox"), "Keep this reason");
  await user.click(screen.getByRole("button", { name: "Record hold" }));
  expect(screen.getByRole("alert").textContent).toContain("Review changed");
  expect(screen.getByRole("textbox").value).toBe("Keep this reason");
  await user.click(screen.getByRole("button", { name: "Refresh review" }));
  expect(refresh).toHaveBeenCalledOnce();
});

test("ID opens the retained submission disclosure", async () => {
  render(<ReviewCard {...props} />);
  await userEvent.click(screen.getByRole("link", { name: "WORK-001" }));
  expect(screen.getByText("Inspect discrepancy").closest("details").open).toBe(
    true,
  );
});

test("unknown checks cannot inherit a count headline or offer an uncollected exception", () => {
  const review = {
    case_id: "case",
    evaluation_status: "completed",
    recommendation: { answer: "no", reason: "Meaning is unknown" },
    allowed_actions: ["record_yes", "record_no"],
    result: {
      requirement_results: [
        {
          status: "unknown",
          explanation: "Meaning is unknown",
          method: { id: "semantic_review" },
        },
      ],
    },
  };
  const display = presentReview(
    review,
    { work_type: "order", work: { declared: 4, supported: 3 } },
    null,
  );
  expect(display.headline).toBe("This work needs attention");
  expect(display.canProceed).toBe(false);
  expect(display.canHold).toBe(true);
  const failed = presentReview(
    {
      ...review,
      evaluation_status: "failed",
      recommendation: null,
      allowed_actions: [],
    },
    {},
    null,
  );
  expect(failed.recommendation).toBe(null);
  expect(failed.canProceed).toBe(false);
});

test("the count review preserves API recommendation prose and bound profile priorities", () => {
  const reason = "Hold until the source record can be reconciled.";
  const review = {
    case_id: "case",
    evaluation_status: "completed",
    recommendation: { answer: "no", reason },
    allowed_actions: ["record_yes", "record_no"],
    result: {
      requirement_results: [
        {
          status: "unmet",
          explanation: "4 versus 3",
          method: {
            id: "equal_values",
            parameters: { left: "/work/declared", right: "/work/supported" },
          },
        },
      ],
    },
  };
  const risks = [
    { id: "risk-a", consequence: "Processing slows", applies_to: "hold" },
    { id: "risk-b", consequence: "Additional rework", applies_to: "proceed" },
  ];
  const display = presentReview(
    review,
    { work_type: "order", work: { declared: 4, supported: 3 } },
    { definition: { risks } },
  );
  expect(display.headline).toBe("This work needs attention");
  expect(display.explanation).toBe(reason);
  expect(display.holdRisks).toEqual([{ ...risks[0], priority: 1 }]);
  expect(display.proceedRisks).toEqual([{ ...risks[1], priority: 2 }]);
  render(<ReviewCard {...display} />);
  expect(
    screen
      .getByText("Priority 2")
      .compareDocumentPosition(
        screen.getByRole("button", { name: "Proceed" }),
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(screen.queryByText(/Risk priorities:/)).toBe(null);
});

test("unavailable action help opens by keyboard beside its button and closes with Escape", async () => {
  const user = userEvent.setup();
  render(
    <ReviewCard
      {...props}
      proceedUnavailableReason="Resolve the missing evidence first."
    />,
  );
  const help = screen.getByLabelText("Why is Proceed unavailable?");
  expect(help.getAttribute("aria-expanded")).toBe("false");
  expect(
    help.parentElement.parentElement.parentElement.contains(
      screen.getByRole("button", { name: "Proceed" }),
    ),
  ).toBe(true);
  help.focus();
  await user.keyboard("{Enter}");
  expect(help.getAttribute("aria-expanded")).toBe("true");
  await user.keyboard("{Escape}");
  expect(help.getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(help);
  await user.click(help);
  expect(help.getAttribute("aria-expanded")).toBe("true");
});
