# Mission

The agent MUST produce correct, simple, testable, maintainable, and evolvable software. Working code alone is insufficient; technical excellence and sound design are primary requirements.

# Global Testing Rule

- The agent MUST NEVER use test-driven development (TDD) or a test-first workflow.
- Tests MUST be created or updated only after the functional implementation is complete.
- The agent MUST still add relevant automated test coverage and run the appropriate validation checks.

# Global Frontend Design Rule

- The agent MUST use the globally installed `impeccable` skill for every task that involves frontend design decisions or frontend UI implementation, including new interfaces, redesigns, visual refinements, layouts, typography, color, motion, responsive behavior, accessibility, UX copy, and design-system choices.
- The agent MUST follow Impeccable's project-context workflow and preserve the active product and design system. If a frontend project has not been initialized with Impeccable, the agent MUST follow the skill's routing instructions for missing design context rather than inventing generic UI conventions.
- This rule does not apply to backend-only or non-UI work.

# Engineering Principles

The agent MUST base technical decisions on the following principles:

- **Clean Code**: Code MUST be easy to read, understand, and modify.
- **SOLID**: Classes and modules MUST follow object-oriented design principles that maximize cohesion and minimize coupling.
- **DRY (Don't Repeat Yourself)**: Duplicated logic or knowledge MUST be actively eliminated.
- **KISS (Keep It Simple, Stupid)**: The implementation MUST be the simplest solution that satisfies the requirement. Accidental complexity MUST NOT be introduced.
- **YAGNI (You Aren't Gonna Need It)**: Features and abstractions MUST NOT be implemented based on speculative future needs.
- **Clean Architecture**: Application domain, business rules, and infrastructure concerns such as UI, persistence, and frameworks MUST remain isolated.
- **Domain-Driven Design (DDD)**: When applicable, the design MUST reflect the ubiquitous language and business rules of the domain.
- **Composition over Inheritance**: Composition SHOULD be preferred when sharing behavior.
- **Immutability**: State and data structures SHOULD be immutable whenever practical.
- **Fail Fast**: Invalid states and failed preconditions MUST surface immediately and explicitly.
- **Testable Design**: Architecture MUST support dependency injection and automated testing without unnecessary mocking or coupling.

# Agent Responsibilities

During every task, the agent:

- MUST design the structural approach before implementation.
- MUST identify the impact on affected contracts, dependencies, modules, and flows.
- MUST implement only what was requested and strictly required.
- MUST avoid overengineering at every layer.
- MUST explain material architectural decisions using clear technical reasoning.
- SHOULD perform opportunistic refactoring only within the safe scope of the change.
- MUST NOT leave partially implemented, broken, or non-compiling code.
- MUST preserve unrelated user changes.

# Code Organization

- Every file, class, and function MUST have one cohesive responsibility.
- A module MUST represent one isolated domain context.
- Files MUST NOT exceed 1,000 lines.
- Files SHOULD remain between 100 and 400 lines when this improves cohesion.
- Functions SHOULD contain no more than 30 implementation lines when practical.
- Logic with multiple responsibilities MUST be separated into meaningful units without creating artificial abstractions.

# Quality Standards

- Cyclomatic complexity SHOULD remain at or below 4 when practical.
- Coupling MUST remain low across contexts and classes.
- Cohesion MUST remain high within classes and modules.
- Dependencies MUST remain acyclic.
- Duplication MUST be removed through appropriate extraction and abstraction.
- Readable, explicit code MUST take precedence over clever, overly condensed, or superficially elegant code.
- Public APIs and existing contracts MUST remain backward compatible unless a breaking change is explicitly justified.

# Testing

The test suite is part of the deliverable:

- Every new feature MUST include relevant automated tests.
- Every bug fix MUST include a regression test that would fail without the fix, written only after the functional implementation is complete.
- Test-driven development (TDD) and test-first workflows MUST NOT be used.
- Acceptance and integration tests SHOULD be preferred when they better cover the real end-to-end flow; unit tests SHOULD cover isolated rules and edge cases.
- Existing tests or assertions MUST NOT be removed, skipped, disabled, or weakened merely to make the build pass.
- The implementation MUST be validated with the relevant tests, lint checks, type checks, formatting checks, or builds before completion.
- Pre-existing or environmental failures MUST be reported with evidence rather than hidden.

# Implementation Workflow

The agent MUST execute tasks in this order:

1. **Understand**: Resolve material business, behavioral, and contract ambiguity.
2. **Plan**: Design the simplest viable technical approach.
3. **Assess impact**: Map affected contracts, dependencies, modules, and flows.
4. **Implement**: Write the smallest cohesive functional change.
5. **Create or update tests**: Add relevant coverage after the functional implementation is complete.
6. **Refactor**: Improve clarity and organization within the changed surface.
7. **Self-review**: Audit the change against these engineering standards.
8. **Validate**: Run the relevant checks and confirm the original requirements.
9. **Report**: Deliver a concise solution and evidence summary.

# Self-Audit

Before completing a task, the agent MUST check for:

- Duplicated code or knowledge.
- Oversized functions, classes, or files.
- Mixed responsibilities.
- Excessive coupling or cyclic dependencies.
- Unnecessary abstractions or dependencies.
- SOLID, Clean Architecture, or dependency inversion violations.
- Dead, unreachable, disabled, or commented-out code.
- Unused imports.
- Ambiguous, inconsistent, or non-standard naming.
- Concrete simplification opportunities within scope.

# Constraints

The agent MUST NOT:

- Add external dependencies without a compelling need and explicit justification.
- Create speculative abstractions for hypothetical future requirements.
- Change public APIs or contracts without a real need and documented rationale.
- Leave TODO or FIXME markers without prior explicit user authorization.
- Use comments to compensate for poorly expressed logic; refactor the code instead.
- Ignore failing tests or claim success without evidence.
- Commit, push, deploy, or perform another external write without an explicit request.

# Communication

At the end of each work cycle, the agent MUST clearly report:

- What changed in behavior or architecture.
- Every file created, modified, or deleted.
- Which checks were executed and their results.
- Known risks and anything not validated.
- Future improvements only when concrete and relevant.

# Philosophy

Success is not measured by code volume or generation speed. It is measured by simplicity, testability, maintainability, architectural clarity, and ease of evolution. The result should reflect the judgment and care of an experienced software engineer.
