# Discord Gateway Doctor

A [Hermes Agent](https://hermes-agent.nousresearch.com/) skill that explains why a Discord gateway is offline or online-and-silent. It reads a local Hermes home, classifies the usual fail-closed and privileged-intent mistakes, and never prints `DISCORD_BOT_TOKEN`.

This is a community skill, not part of the Hermes repo. Share it in the Nous Research Discord `#plugins-skills-and-skins` channel. It credits [Mining (TurgayAcar49)](https://github.com/TurgayAcar49). Hermes expects the person first and the agent second, which is the `author` line in `SKILL.md`.

## Install

Copy the skill into the Hermes skills directory:

```bash
mkdir -p ~/.hermes/skills/devops
cp -R skills/devops/discord-gateway-doctor ~/.hermes/skills/devops/
```

Then, in a new Hermes session, ask it to diagnose the Discord gateway. The skill runs:

```bash
python ~/.hermes/skills/devops/discord-gateway-doctor/scripts/doctor.py --json
```

Add `--live` only when you want a token and intent check against `https://discord.com`. The token stays in `.env`. It is not an argument.

Exit codes: `0` ok, `1` warning, `2` error.

## What a reviewer can check

```bash
python -m unittest tests/test_discord_gateway_doctor.py -v
```

The script uses only the Python standard library.

## Discord post

After the tests pass, post this in `#plugins-skills-and-skins`:

> Community skill: discord-gateway-doctor, by Mining (https://github.com/TurgayAcar49/discord-gateway-doctor, Discord Alyan4916). It classifies a Hermes Discord gateway that is offline or silent (missing token, fail-closed allowlist, privileged intents, username-vs-snowflake allowlists) without printing DISCORD_BOT_TOKEN. Optional `--live` checks the token and Message Content / Server Members flags against Discord. Install by copying `skills/devops/discord-gateway-doctor` into `~/.hermes/skills/devops/`.

## Layout

```
skills/devops/discord-gateway-doctor/
  SKILL.md
  scripts/doctor.py
  references/failure-classes.md
tests/test_discord_gateway_doctor.py
```
