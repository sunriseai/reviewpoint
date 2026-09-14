/** The credential stays in memory. Uncertain retries reuse the original mutation key. */
export function createApi(credential) {
  const pending = new Map();
  async function api(path, method = "GET", body) {
    const signature = JSON.stringify([path, method, body]);
    const mutation = method !== "GET";
    if (mutation && !pending.has(signature))
      pending.set(signature, crypto.randomUUID());
    const response = await fetch(path, {
      method,
      headers: {
        Authorization: `Bearer ${credential}`,
        "Content-Type": "application/json",
        ...(mutation ? { "Idempotency-Key": pending.get(signature) } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const value = await response.json();
    if (!response.ok) {
      if (response.status < 500) pending.delete(signature);
      const error = Error(
        value.error?.code === "stale_review"
          ? "This review changed. Refresh, inspect the current result, then confirm again. Your reason is retained."
          : value.error?.message || value.detail || "Request failed",
      );
      error.status = response.status;
      throw error;
    }
    pending.delete(signature);
    return value;
  }
  api.all = async (path) => {
    const items = [];
    let cursor;
    do {
      const page = await api(
        path +
          (cursor
            ? `${path.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(cursor)}`
            : ""),
      );
      items.push(...page.items);
      cursor = page.next_cursor;
    } while (cursor);
    return items;
  };
  return api;
}
