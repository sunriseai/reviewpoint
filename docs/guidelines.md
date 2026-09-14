# Establishing and managing risk guidelines

In the UI, **Risk guidelines** are versioned API **profiles**. An owner can create a profile or edit one; reviewers and approvers can inspect it. Use the example owner credential to explore authoring.

## Start with consequences

Write what might happen: “Incomplete work reaches the next step,” “Additional effort to correct released work,” or “The next step waits for a correction.” A missing value is an observation that may lead to a consequence, rather than a risk by itself.

Give each risk a short label, a consequence and an association with Proceed, Hold or Both. Reorder with the up/down controls. The review card shows those priorities with the consequences above each action. Association does not force the recommendation, and ranking never waives requirements.

## Add requirements

The guided editor supports:

- **Required value:** select a field that must contain a supplied value.
- **Values agree:** select two supplied fields to compare. Comparisons are strict, including value types.

Select fields from the example's field catalog and associate every requirement with at least one risk. A risk cannot be removed while requirements reference it. An empty field and an unavailable field can produce different results; inspect the requirement explanation and references.

The API supports other check methods, applicability rules, freshness rules and limited exceptions. Requirements outside the guided editor's methods or field catalog are labeled **API-managed** and preserved unchanged. The editor does not convert or drop them. Scope and review-rule settings are retained when publishing.

## Publish deliberately

Edits remain local to the form until publication. A name, at least one risk, at least one requirement, valid associations and a publication reason are required. Cancel discards unsaved edits. Publication produces a new immutable version and detects conflicts with another publisher.

Existing reviews continue to display the version used for their assessment. Select the new version under **Reviews → Select guidelines and evaluate** to apply it. A new assessment requires a new decision; old records remain in history.

A technical pass cannot tell an owner whether the guidelines capture the right consequences. Challenge the example by removing an important requirement, observing the resulting recommendation and raising a concern. The service records the decision process; people remain responsible for whether the standard is adequate.
