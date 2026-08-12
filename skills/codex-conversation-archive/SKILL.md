---
name: codex-conversation-archive
description: Export visible, unarchived Codex conversations for the current day as sanitized Markdown in a repository, with a protected-main fallback and remote confirmation.
---

# Codex conversation archive

Use this skill only when explicitly invoked as `$codex-conversation-archive`.
The workflow is deterministic and must run at 23:30 in `America/Sao_Paulo`.

## Inputs and scope

1. Use the automation's configured working directory only as the workspace
   context. The publication target is always `mehiel-victor/tools`; if that
   repository cannot be resolved or authenticated, stop without changing files.
2. Resolve today's date in `America/Sao_Paulo` at execution time. Select only
   tasks with `archived=false` that contain at least one visible
   user or assistant message whose event date is today in that timezone. Do not
   include hidden, system-only, deleted, or undated messages.
3. The `archived` value is a read-only filter. Never mutate conversation status
   or add archive markers. Idempotency comes from deterministic thread IDs,
   message IDs/timestamps, and output names; reruns overwrite identical bytes.

## Isolated work and export

1. Create a fresh isolated clone in a workspace-owned `work` directory. Never
   use `/tmp` or modify a shared checkout. Confirm its `origin` is exactly
   `https://github.com/mehiel-victor/tools` (allowing the equivalent SSH URL),
   fetch `origin`, check out `main`, and fast-forward to `origin/main` before
   generating files. Never archive credentials from the work directory.
2. Apply the date, visibility, and role predicate again to every message being
   rendered: include only visible user or assistant messages dated today in
   `America/Sao_Paulo`. Never render earlier or later messages merely because
   their thread qualified for export.
3. In the isolated work directory, render the daily directory
   `codex-conversations/YYYY/MM/YYYY-MM-DD/`. Write one Markdown file per
   conversation, named only with its sanitized stable thread ID, plus a
   deterministic `index.md` listing thread IDs and counts derived only from the
   filtered messages. Do not place titles, message text, local paths, or other
   conversation metadata in filenames. Sort threads and messages by stable IDs
   then event time, and use UTF-8 and deterministic newline formatting. A rerun
   with the same source data must produce identical bytes.
4. Export only message text and non-sensitive conversation metadata needed to
   identify the task. Do not export attachments, hidden metadata, local paths,
   machine identifiers, or provider payloads.

## Secret sanitization (mandatory)

Sanitize before writing Markdown and again before staging. Replace values with
`[REDACTED]` and preserve surrounding prose. Redact bearer/basic/API tokens,
OAuth and session tokens, cookies, webhook signatures, passwords, private keys,
cloud credentials, and values of fields named (case-insensitively) `token`,
`secret`, `password`, `api_key`, `apikey`, `authorization`, `cookie`, or
`private_key`. Redact secrets embedded in URLs (query strings and user-info),
JSON/YAML assignments, shell exports, JWTs, PEM blocks, and common provider key
prefixes. Treat any uncertain high-entropy credential-looking value as a
secret. Never attempt to recover or print the original value in logs, diffs,
errors, or pull requests. If sanitization cannot be proven complete, stop and
leave the source conversations untouched.

## Commit, protected-main fallback, and confirmation

1. Review the generated diff, verify no work-directory files are staged, run the
   repository's available checks, and fail closed on any check or sanitization
   error. Do not force push.
2. Commit the archive on the local `main` branch and push to `origin/main`.
3. If `main` is protected and a direct push is rejected, keep the commit,
   create a uniquely named non-default branch, push it to `origin`, and prepare
   a pull request targeting `main` with checks required. Use the repository's
   normal PR interface; do not guess undocumented Codex or provider endpoints.
   When policy permits automatic merge, use squash merge only after required
   checks pass. Otherwise leave the PR ready for review and report its URL.
4. Confirm the resulting archive commit is reachable from `origin/main` (or,
   while a protected-branch PR is pending, report the exact pending state).
   Record the commit SHA, date, exported task count, and outcome without
   including message content or secrets.
5. Conversation status is never changed by this workflow. On any failure,
   report a concise actionable error and preserve the isolated work directory
   for inspection unless it contains unsanitized data, in which case remove it
   securely and report only that cleanup occurred.
