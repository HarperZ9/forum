---
name: forum-route-preflight
description: Preview Forum routing, context and runtime readiness before considering dispatch.
---

# Forum route preflight

Use the bundled MCP tools. This client package needs no globally installed Forum
CLI. The source ZIP needs Python; the native Windows package includes its runtime.

1. Call forum.status to inspect the bundled version.
2. Call forum.route with the user's task in `text`.
3. Compare the result with any user-selected lane. A mismatch or escalation is a
   finding, not permission to dispatch or change the user's task.
4. Call forum.context.preflight with the task in `request`. The packaged server
   uses an empty in-memory ledger, so it cannot recover an existing run's capsule.
5. Call forum.prose.contract with the task in `text` and the relevant delivery profile.
6. Call forum.runtime.inspect. No model executor is configured by this package.
7. Report route, confidence, escalation, context result and missing execution
   readiness. A route is lexical evidence, not a competence proof.

This package never submits work, authorizes a gate, configures an executor,
installs hooks or makes model calls. A separate explicitly configured Forum
execution surface is needed for user-authorized execution. Do not infer that
permission from installing this skill or from a successful preflight.

The bundled helper and references preserve Forum's existing CLI preflight workflow
for advanced source users. They are optional, and no pip installation is required
for this MCP workflow.
