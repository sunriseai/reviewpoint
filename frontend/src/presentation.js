/** Map frozen API records to the card. No authority or policy lives here. */
export function presentReview(review, submission, profile, externalId) {
  const checks = review.result?.requirement_results || [];
  const blockers = checks.filter((r) =>
    ["unmet", "unknown"].includes(r.status),
  );
  const ready = review.evaluation_status === "completed";
  const recommendation = ready ? review.recommendation?.answer : null;
  const risks = (profile?.definition?.risks || []).map((r, i) => ({
    ...r,
    priority: i + 1,
  }));
  const canProceed =
    ready &&
    review.allowed_actions.includes("record_yes") &&
    blockers.length === 0;
  const canHold = ready && review.allowed_actions.includes("record_no");
  return {
    systemId: externalId || review.case_id,
    action: review.proposed_action?.label || "Review the proposed action",
    headline: !ready
      ? review.evaluation_status === "failed"
        ? "Evaluation could not finish"
        : review.evaluation_status === "pending"
          ? "Evaluation in progress"
          : "Awaiting evaluation"
      : recommendation === "yes"
        ? "The supplied checks are satisfied"
        : "This work needs attention",
    bullets: blockers.length
      ? blockers.slice(0, 3).map((r) => r.explanation)
      : ready
        ? ["All applicable requirements have qualifying support."]
        : [],
    proceedRisks: risks.filter((r) =>
      ["proceed", "both"].includes(r.applies_to),
    ),
    holdRisks: risks.filter((r) => ["hold", "both"].includes(r.applies_to)),
    recommendation,
    explanation:
      (ready ? review.recommendation?.reason : review.error?.message) ||
      (ready
        ? "No recommendation explanation was provided."
        : review.evaluation_status === "pending"
          ? "Wait for the evaluation to finish before deciding."
          : "Request an evaluation before deciding."),
    canProceed,
    canHold,
    proceedUnavailableReason: canProceed
      ? ""
      : blockers.length
        ? "Unmet or unknown requirements need resolution or an authorized exception. This demo cannot record exceptions."
        : "Proceed is unavailable with your current access and review state. Refresh the review to check for changes.",
    holdUnavailableReason: canHold
      ? ""
      : "Hold is unavailable with your current access and review state. Refresh the review to check for changes.",
    evidence: submission?.evidence,
    submission,
  };
}
