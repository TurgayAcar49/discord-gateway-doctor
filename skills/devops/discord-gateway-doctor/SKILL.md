---
name: discord-gateway-doctor
description: Diagnose a silent or offline Hermes Discord gateway.
version: 0.1.0
author: Set your name before publishing
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Discord, Gateway, Diagnostics]
---

# Discord Gateway Doctor

Classify why a Hermes Discord gateway is offline or connected-but-silent. The check reads the local Hermes home and, only with `--live`, Discord's API. It does not print the bot token and it does not edit config.

## When to Use

- The Discord bot never comes online, or comes online and ignores every message.
- Gateway startup mentions privileged intents, an improper token, or a missing access policy.
- An allowlist was edited and it is unclear whether Hermes will actually authorize anyone.

Don't use for:

- Building a Discord bot that is not the Hermes gateway.
- Granting roles on the Nous Research Discord server.
- Reading or copying `DISCORD_BOT_TOKEN`. If a command would print `.env`, stop.

## Prerequisites

- A Hermes home, normally `~/.hermes`, containing `.env` and optionally `config.yaml` and `logs/gateway.log`.
- Python 3.11+ on `PATH`. The script uses the standard library only.
- `--live` needs outbound HTTPS to `discord.com` and a token already stored in `.env`. Never pass the token as an argument.

## How to Run

Offline classification:

`terminal(command="python ${HERMES_SKILL_DIR}/scripts/doctor.py --json", timeout=30)`

When the user agrees to a live token and intent check:

`terminal(command="python ${HERMES_SKILL_DIR}/scripts/doctor.py --json --live", timeout=30)`

A non-default home:

`terminal(command="python ${HERMES_SKILL_DIR}/scripts/doctor.py --json --hermes-home /path/to/hermes-home", timeout=30)`

## Quick Reference

| Exit | Status | Meaning |
| --- | --- | --- |
| 0 | `ok` | Token shape and an access policy are present, and nothing logged a hard failure. |
| 1 | `warn` | Usable, with a risk such as allow-all or a non-numeric user entry. |
| 2 | `error` | The gateway will stay offline or deny everyone until this is fixed. |

## Procedure

1. Run the offline command. Completion: the JSON parses, and every finding has `code`, `message`, and `fix`.
2. Order the reply by `error`, then `warn`, then `info`. Give the user one next action from the highest-severity `fix`. Completion: the reply does not dump unrelated env vars.
3. If the status is not `ok` and the user wants the portal settings checked, run `--live`. Completion: the report includes `token_valid` or `token_rejected`, or a network finding. The token never appears in the command.
4. Stop after the report unless the user asks for an edit. Completion: `.env` and `config.yaml` are unchanged.
5. When a `fix` names a portal toggle or a restart, say that a file edit does nothing until `hermes gateway restart`. Completion: the reply includes the restart only when a setting change is required.

Code-by-code causes live in `references/failure-classes.md`. Load that file with `read_file` when the user wants the longer explanation of a code.

## Pitfalls

- Message Content Intent off keeps the bot offline. A missing allowlist leaves it online and silent. Do not swap those two fixes.
- `DISCORD_ALLOWED_USERS` may contain usernames. Role and channel lists may not. Display names and nicknames never match.
- `DISCORD_ALLOW_ALL_USERS=true` satisfies the fail-closed check and still exposes the agent's tools to every person who can message the bot.
- `gateway.log` can describe the previous process. If `no_access_policy_logged` is `info`, the files are already fixed and the process needs a restart.
- `--live` cannot see a toggle that was saved in the portal but not yet reflected on `GET /applications/@me`. Trust a fresh portal save plus a restart over a stale flag.

## Verification

The run worked when the command exits 0, 1, or 2 and the JSON `status` matches that exit code (`ok`, `warn`, `error`). Quote the `code` values you acted on. A successful live check includes `token_valid` and `message_content_intent_on` or `message_content_intent_off`.
