# Deep Trace Verification

When verifying that an implementation actually works, trace every call chain to its leaf — the point where data is actually read, written, sent, or received. Never stop at a call boundary you haven't verified. Follow the data, not the assumption.

A "leaf" depends on the project: a database query, an HTTP request, a filesystem operation, a message queue publish, a subprocess exec, a hardware I/O call, a rendered UI element. Whatever the final side effect is — verify it.

## Checklist

1. **Entry point exists and is reachable** — verify the trigger that starts this code path actually invokes it. For a web API: does the route match what callers send, accounting for any path rewrites or middleware? For a CLI: is the command/subcommand registered? For a UI: is the event handler wired to the element? For a worker: is the job/message subscription active?

2. **Each layer calls the next correctly** — at every call boundary, verify the callee exists, accepts the arguments being passed, and returns what the caller expects. Don't stop at `someService.doThing(...)` and assume it works — read `doThing` and confirm.

3. **Referenced resources exist** — if the code looks up a named resource (a config key, a template name, a queue name, a DB record, an environment variable, a file path, a route, a translation key), verify that resource actually exists where the code expects it. A function that calls `loadTemplate("welcome_email")` is broken if that template was never created.

4. **Data shape is consistent end-to-end** — trace each value from where it originates, through every transformation and handoff, to where it is consumed. Verify the name, type, and unit are correct at every boundary. A field called `duration` set in seconds but read as milliseconds ships broken behavior silently.

5. **Error and absence paths are handled** — at each layer, ask: what happens if this call fails, returns null, returns empty, or throws? Is the failure surfaced or silently swallowed? Does the caller handle it or crash?

The short version: trace until you hit an actual leaf. Stop when you've verified each node exists and the data flowing through it is correct. Anything less is half a trace.
