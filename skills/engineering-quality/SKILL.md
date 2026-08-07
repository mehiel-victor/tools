---
name: engineering-quality
description: Apply Victor's engineering standards to feature work, bug fixes, refactoring, architecture decisions, and code review. Use when implementation must emphasize simplicity, testability, maintainability, SOLID and Clean Architecture boundaries, regression coverage, focused validation, and an explicit delivery audit.
---

# Engineering Quality

## Workflow

1. Restate the requested behavior and resolve material business or contract ambiguity.
2. Identify affected modules, public APIs, dependencies, data flows, and tests.
3. Choose the smallest design that satisfies the requirement without speculative abstractions.
4. Add or update tests before implementation. For bugs, demonstrate the defect with a failing regression test first.
5. Implement the narrowest cohesive change while preserving unrelated edits and compatible contracts.
6. Refactor only the changed surface for clarity, single responsibility, low coupling, and high cohesion.
7. Run the focused tests plus relevant lint, type-check, build, or formatting checks.
8. Audit the final diff and report evidence, risks, and unverified points.

## Design constraints

- Prefer explicit, readable code over clever compression.
- Apply DRY only to real duplicated knowledge; do not manufacture premature abstractions.
- Keep domain rules independent from UI, persistence, frameworks, and other infrastructure.
- Prefer composition and immutable state where they simplify behavior.
- Fail fast on invalid state and precondition violations.
- Keep dependencies acyclic and avoid external packages unless clearly necessary and approved.
- Keep files below 1000 lines, target cohesive files of roughly 100-400 lines, and prefer functions under 30 lines when practical.
- Do not leave unauthorized TODO/FIXME markers, dead code, disabled assertions, ignored failures, or commented-out implementations.

## Validation and review

Check the final change for behavioral regressions, missing edge cases, duplication, mixed responsibilities, high cyclomatic complexity, contract breaks, security or reliability risks, unused imports, and naming ambiguity. Never weaken or remove existing tests merely to obtain a green result. Classify environmental or pre-existing failures honestly and include the shortest useful evidence.

## Delivery format

Report:

- Behavior changed and architectural decisions made.
- Files created, edited, or deleted.
- Tests and checks executed with results.
- Known risks and anything not validated.
- Concrete future improvements only when relevant.
