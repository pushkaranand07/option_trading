// The page's only way to call the server.
// The page's only fetch. A request that changes anything (not GET) carries X-Pulse-Request: 1, which the server
// requires: another website open in the browser cannot add it, so it cannot take or close trades through this server.
export async function api(path, opts) {
  const method = (opts?.method || "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD") {         // Headers keeps the caller's headers whether given as an object, a list or a Headers
    const headers = new Headers(opts.headers); headers.set("X-Pulse-Request", "1");
    opts = { ...opts, headers };
  }
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {                            // a detail may be an object (409: {message, ...}); the message is what is shown
    // 409: {message, ...}; 422 (FastAPI validation): a list of {loc, msg}; else a string.
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d?.msg).filter(Boolean).join("; ") : body.detail;
    const msg = (typeof detail === "object" ? detail?.message : detail) || `HTTP ${r.status}`;
    const e = new Error(body.error_id ? `${msg} (error id ${body.error_id}; the server log has the details)` : msg);
    e.status = r.status; e.detail = body.detail; e.errorId = body.error_id;
    throw e;
  }
  return body;
}
