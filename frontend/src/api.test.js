import { afterEach, expect, test, vi } from "vitest";
import { createApi } from "./api.js";
import { revisedSubmission } from "./ExampleHost.jsx";
afterEach(() => vi.unstubAllGlobals());
test("uncertain retries retain the mutation key and successful operations get a new one", async () => {
  const fetch = vi
    .fn()
    .mockRejectedValueOnce(Error("network interrupted"))
    .mockResolvedValue({ ok: true, json: async () => ({ saved: true }) });
  vi.stubGlobal("fetch", fetch);
  const api = createApi("local-test-token");
  const body = { reason: "Human reason" };
  await expect(api("/operation", "POST", body)).rejects.toThrow("network");
  await api("/operation", "POST", body);
  await api("/operation", "POST", body);
  const key = (i) => fetch.mock.calls[i][1].headers["Idempotency-Key"];
  expect(key(0)).toBe(key(1));
  expect(key(2)).not.toBe(key(1));
});
test("host revisions preserve action identity and reference the exact prior submission", () => {
  const previous = {
    submission_id: "s1",
    revision: 3,
    work_type: "work_item",
    action: { type: "release_work", target: "simulation", parameters: {} },
    context: { note: "synthetic" },
  };
  const body = revisedSubmission(previous, {
    summary: "Updated",
    expected_items: 4,
    supplied_items: 4,
  });
  expect(body.expected_submission_id).toBe("s1");
  expect(body.host_revision).toBe("revision-4");
  expect(body.proposed_action).toEqual(previous.action);
  expect(JSON.parse(body.evidence[0].content)).toEqual(body.work);
});
