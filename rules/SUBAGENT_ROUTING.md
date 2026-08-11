# Subagent Routing

Optimize first for correctness, simplicity, testability, and maintainability. Treat cost and latency as secondary constraints. Delegate when a specialized agent improves evidence quality, isolates context, or creates meaningful independent review; do not delegate merely because a cheaper model exists. The parent retains responsibility for ensuring that all work follows `ENGINEERING_STANDARDS.md`.

At the start of a broad task, identify separable workstreams and delegate only bounded, non-overlapping slices with explicit ownership. Reassess after significant checkpoints. Keep tightly coupled work local when delegation would duplicate discovery, obscure architectural decisions, or create integration risk.

The parent agent retains ownership of architectural decisions, experiment selection, integration, and concise final validation. Delegate bounded workstreams, not the overall objective. Keep tightly coupled experiment-selection loops in the parent; delegate experiment execution or result analysis when independently separable. Every delegated implementation task must have explicit, non-overlapping file or module ownership; agents share the workspace, must preserve unrelated edits, and must accommodate concurrent changes.

Execute directly only for truly trivial operations where agent startup would exceed the work: a single known-line edit, one short command, or a factual response. Do not delegate trivial conversation. The parent may run ordinary commands needed for routing, integration, or concise final verification, but should delegate repository execution rather than handling substantial discovery, implementation, conflict resolution, or review itself. A slow command alone is not a reason to delegate runner work; use an execution agent when diagnosis, output analysis, or independent parallel execution is substantial.

When delegation is justified:

- Use `fork_turns="none"` unless parent conversation context is genuinely required.
- Prefer one subagent per task. Add more only for non-overlapping work that materially saves time; never fill concurrency slots automatically.
- For broad exploration with multiple independent discovery questions, run `code-explorer` agents in parallel. Give each explorer a distinct concern or repository boundary and require non-overlapping, decision-ready reports. Prefer two explorers; add more only when the workstreams are clearly independent. Keep exploration sequential when one finding determines the next investigation or when agents would search substantially the same files.
- Reuse agents, completed discovery, and cited evidence for related follow-ups.
- Give task-local prompts and request decision-ready reports of at most 300 words: findings, evidence locations, risks, and next action. Exclude narration, raw dumps, and repeated context.
- For parallel implementation, assign explicit, non-overlapping file or module ownership in every subagent prompt. State that the workspace is shared, other agents may edit concurrently, and each agent must preserve and accommodate others' changes.
- Trust cited findings unless verification is necessary. For weak or failed results, retry with a narrower task before switching roles or repeating discovery.
- Detach behavioral verification from `implementer` by default. After implementation and cheap structural checks, keep the original implementer available and delegate focused test, build, lint, or type-check scopes to `code-validator`. Build a complete affected-test manifest from every added or changed test file plus directly affected existing tests. Every validator prompt must state the exact targeted command, assigned manifest entries, scope, and concurrency plan. Run all manifest entries with test-file, test-class, package, or equivalent selectors instead of substituting a whole-suite command; for example, use Gradle `test --tests ...` selectors. Prefer one validator using up to three test-runner workers when supported and concurrency-safe. Otherwise partition the complete manifest across up to three `code-validator` agents with distinct, non-overlapping shards; each shard may contain multiple test selectors. Three limits concurrent workers or agents, not the number of affected tests that must run. Do not parallelize commands that share mutable databases, fixtures, snapshots, generated files, ports, caches, or coverage outputs unless those resources are isolated.
- When every affected unit-test manifest entry passes, do not rerun the global unit-test suite by default. Treat integration and end-to-end validation as separate scopes only when explicitly required by the task or a later routing policy. The parent classifies validator failures before requesting repairs. Consolidate likely implementation failures and resume the same implementer with `followup_task` so it retains its context and file ownership, then send the affected checks back to a validator. Prefer no more than two repair cycles before escalating unresolved, flaky, environmental, or contract-level failures.
- For a truly trivial change with one fast and obvious check, `quick-implementer` may validate directly instead of spawning a validator.

Every implementation assignment must require the smallest viable change, affected-test coverage, compatibility with existing contracts, no unauthorized dependencies or TODO markers, and an explicit validation manifest. Test-driven development and test-first workflows must never be used. Bug-fix regression tests must be written only after the functional implementation is complete. Validation failures must be reported rather than bypassed or hidden.

Select custom agents by their exact `name` from `~/.codex/agents`:

- Broad repository discovery, contract or data-flow tracing -> `code-explorer`
- Mechanical one- or two-file change -> `quick-implementer`
- Multi-file behavior change, debugging, or substantial tests -> `implementer`
- Focused read-only test, build, lint, or type-check execution -> `code-validator`
- Independent review only for high-risk, security-sensitive, architectural, public-API, migration, concurrency, or difficult-to-validate changes -> `code-reviewer`
- Commit and push, only when the user explicitly requests both -> `commit-pusher`

Do not use a fixed command-count threshold for exploration. Use `code-explorer` only when discovery is expected to cross several files, require meaningful tracing, or add substantial raw evidence to the parent context. Do not use it to reread known files.

Use the least expensive role and reasoning effort that can satisfy the required quality bar without increasing integration risk. Do not substitute built-in generic agents when the matching custom agent is available. Avoid parallel write-heavy delegation.
