# Subagent Routing

Optimize for execution quality, context efficiency, cost, and wall-clock time. The main agent is the default owner of the work. Group related work into logical phases; never fragment a request into one agent per microtask.

## Hard Limits

- Use at most 3 subagents across the entire user task, including explorers, implementers, validators, reviewers, and publishing agents. This is a total task limit, not a target to fill.
- Assign each subagent exactly one cohesive block containing 5 to 6 meaningful tasks. Meaningful tasks are investigations, file or module groups, implementation outcomes, validation checks, or deliverables—not individual shell commands.
- The 5 to 6 tasks in a block MUST share one goal, one working context, and one decision-ready output. Never pad a block with artificial tasks merely to reach the minimum.
- If fewer than 5 cohesive tasks can be formed, keep the work in the main agent.
- Never create one agent per file, endpoint, test, check, finding, or small edit.
- Subagents MUST NOT spawn or delegate to additional agents. They complete their assigned block themselves and return one concise report.
- Reuse the same subagent with a follow-up when its existing context and ownership remain relevant; do not create a replacement agent for the next microstep.

## Main-Agent Ownership

The main agent retains requirements, architecture, task decomposition, decisions, integration, conflict resolution, and final validation. It MUST directly handle:

- Quick, self-contained refactors.
- Small or localized edits, including one- or two-file changes.
- Tightly coupled investigation and implementation loops.
- Routine commands, focused checks, and concise final verification.
- Any work that cannot be grouped into a substantial 5-to-6-task subagent block.

Do not automatically split implementation, validation, and review among separate agents. The agent that owns a cohesive phase should complete that phase, including proportionate validation, unless a later phase is independently substantial enough to satisfy the same 5-to-6-task rule.

## When to Delegate

- Heavy codebase scanning MUST be delegated to one `code-explorer` with a 5-to-6-task exploration block, such as mapping entry points, tracing contracts, locating callers, finding existing patterns, identifying relevant validation surfaces, and reporting risks.
- Delegate implementation only when it forms a substantial, cohesive phase of 5 to 6 tasks with explicit, non-overlapping file or module ownership.
- Delegate validation or review only when it is independently substantial, high-risk, or evidence-heavy and can be expressed as 5 to 6 cohesive checks. Otherwise the main agent performs it.
- Use parallel subagents only for genuinely independent phases with non-overlapping context and ownership. Prefer sequential reuse when one result determines the next action.
- Avoid parallel write-heavy delegation. Shared-workspace agents must preserve unrelated user changes and accommodate concurrent edits.

## Orchestration

1. Group the request into logical phases before deciding whether to delegate.
2. Keep compact or tightly coupled phases in the main agent.
3. For each delegated phase, provide 5 to 6 explicit tasks, a clear boundary, expected evidence, and a single output format.
4. Request a decision-ready report of at most 300 words: conclusion, evidence locations, risks, and next action. Exclude narration and raw dumps.
5. Integrate results in the main agent. Do not create extra agents merely to summarize, relay, or re-check another agent's output.

## Custom Agent Selection

Select custom agents by exact `name` from `~/.codex/agents` only when the delegation rules above are satisfied:

- Heavy repository discovery, contract tracing, or data-flow mapping -> `code-explorer`
- Substantial cohesive implementation phase -> `implementer`
- Substantial focused non-test validation phase -> `code-validator`
- Independent review only for high-risk, security-sensitive, architectural, public-API, migration, concurrency, or difficult-to-validate changes -> `code-reviewer`
- Commit and push, only when the user explicitly requests both and the publishing phase is delegated as one cohesive block -> `commit-pusher`
- `quick-implementer` is compatibility-only and MUST NOT be selected for quick, self-contained work; the main agent handles that work directly.

Every implementation assignment must require the smallest viable change, compatibility with existing contracts, no unauthorized dependencies or TODO markers, and proportionate non-test validation. Follow `ENGINEERING_STANDARDS.md` throughout.
