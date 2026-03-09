# Deep Trace Verification

When verifying that an implementation actually works, trace every call chain to its leaf — a DB row, SMTP call, filesystem write, or external API response. Never stop at a call boundary you haven't verified. Follow the data, not the assumption.

## Checklist

1. **Entry point → API route** — does the path match what the client sends? Account for every proxy rewrite between them (nginx, application context path, framework path annotations).

2. **Auth/middleware chain** — is this endpoint in the bypass list with the actual post-rewrite URI, not the client-facing URI? Are middleware filters applied in the correct order?

3. **Service layer → downstream calls** — what does the service call? If it calls an external service, trace that call. Don't stop at `someClient.doThing(...)` and assume it works.

4. **Referenced resources exist** — if the code references a named template, queue, configuration entry, or database record, verify it exists. A method that calls `getTemplate("password_reset_requested")` is broken if that row was never inserted.

5. **Variable names end-to-end** — trace each variable from where it's set → how it's passed → what key it's stored under → what the downstream consumer calls it. A type mismatch (e.g., `expiryMinutes` receiving hours) ships broken behavior silently.

The short version: trace until you hit an actual leaf (DB row, SMTP call, filesystem). Stop when you've verified each node exists and the data flowing through it is correct. Anything less is half a trace.
