#!/usr/bin/env python3
"""Diagnose a Hermes Discord gateway that is offline or silent.

Reads the local Hermes home. Prints classifications only. Never prints the
bot token, and the only network call is an optional check against discord.com.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://discord.com/api/v10"
SNOWFLAKE = re.compile(r"^\d{17,20}$")
TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{20,}$")
TOKEN_IN_TEXT = re.compile(
    r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{20,}"
)

# Discord application flags. Either the normal or LIMITED bit means the
# privileged intent toggle is on.
FLAG_GUILD_MEMBERS = 1 << 14
FLAG_GUILD_MEMBERS_LIMITED = 1 << 15
FLAG_MESSAGE_CONTENT = 1 << 18
FLAG_MESSAGE_CONTENT_LIMITED = 1 << 19

LOG_MARKERS = (
    ("privileged_intents_rejected", re.compile(r"privileged Gateway Intents|PrivilegedIntentsRequired", re.I)),
    ("no_access_policy_logged", re.compile(r"No Discord access policy configured", re.I)),
    ("token_rejected_logged", re.compile(r"Improper token|401 Unauthorized", re.I)),
)

TRUE_WORDS = {"1", "true", "yes", "on"}
FALSE_WORDS = {"0", "false", "no", "off"}


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    word = value.strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    return None


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip().strip("'\"") for part in value.split(",") if part.strip()]


def _strip_quote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_discord_block(text: str) -> dict[str, Any]:
    """Extract the top keys of a root-level ``discord:`` mapping.

    Supports scalars and either block lists or inline ``[a, b]`` lists.
    Anything this parser does not understand is ignored.
    """
    result: dict[str, Any] = {}
    lines = text.splitlines()
    in_discord = False
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if not in_discord:
            if indent == 0 and re.match(r"^discord\s*:\s*(?:#.*)?$", stripped):
                in_discord = True
            index += 1
            continue
        if indent == 0:
            in_discord = False
            continue
        match = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.*?)\s*(?:#.*)?$", stripped)
        if not match or indent != 2:
            index += 1
            continue
        key, raw_value = match.group(1), match.group(2).strip()
        if raw_value.startswith("[") and raw_value.endswith("]"):
            inner = raw_value[1:-1].strip()
            result[key] = [_strip_quote(part) for part in inner.split(",") if part.strip()]
            index += 1
            continue
        if raw_value == "":
            items: list[str] = []
            cursor = index + 1
            while cursor < len(lines):
                nxt = lines[cursor]
                nxt_stripped = nxt.strip()
                if not nxt_stripped or nxt_stripped.startswith("#"):
                    cursor += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                if nxt_indent <= indent:
                    break
                if nxt_stripped.startswith("- "):
                    items.append(_strip_quote(nxt_stripped[2:]))
                cursor += 1
            result[key] = items
            index = cursor
            continue
        result[key] = _strip_quote(raw_value)
        index += 1
    return result


def redact(text: str, secrets: list[str]) -> str:
    cleaned = text
    for secret in secrets:
        if secret and len(secret) >= 8:
            cleaned = cleaned.replace(secret, "[redacted]")
    return TOKEN_IN_TEXT.sub("[redacted-token]", cleaned)


def bot_id_from_token(token: str) -> str | None:
    first = token.split(".", 1)[0]
    padded = first + "=" * (-len(first) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            decoded = decoder(padded).decode("ascii")
        except (ValueError, UnicodeDecodeError):
            continue
        if decoded.isdigit():
            return decoded
    return None


def _finding(level: str, code: str, message: str, fix: str) -> dict[str, str]:
    return {"level": level, "code": code, "message": message, "fix": fix}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return split_csv(str(value))


def classify_allowlist(name: str, entries: list[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    bad = [entry for entry in entries if not SNOWFLAKE.match(entry)]
    if not bad:
        return findings
    if name == "DISCORD_ALLOWED_USERS":
        findings.append(
            _finding(
                "warn",
                "username_allowlist",
                "DISCORD_ALLOWED_USERS contains non-numeric entries: " + ", ".join(bad) + ".",
                "Usernames resolve only when Server Members Intent is enabled. Display names and nicknames never match. Prefer numeric user IDs.",
            )
        )
        return findings
    findings.append(
        _finding(
            "error",
            "invalid_id_list",
            f"{name} has entries that are not Discord IDs: " + ", ".join(bad) + ".",
            "Replace each entry with the numeric ID (17-20 digits). Role and channel names are not accepted.",
        )
    )
    return findings


def analyze_config(env: dict[str, str], discord_cfg: dict[str, Any], log_text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    token = env.get("DISCORD_BOT_TOKEN", "").strip()
    secrets = [token] if token else []

    if not token:
        findings.append(
            _finding(
                "error",
                "missing_token",
                "DISCORD_BOT_TOKEN is unset.",
                "Run `hermes gateway setup`, choose Discord, and paste the bot token from the Developer Portal. Restart with `hermes gateway restart`.",
            )
        )
    elif not TOKEN_SHAPE.match(token):
        findings.append(
            _finding(
                "warn",
                "unexpected_token_shape",
                "DISCORD_BOT_TOKEN is set but does not look like a Discord bot token.",
                "Reset the token in the Developer Portal and save the new value. Do not use a user account token.",
            )
        )
    else:
        findings.append(
            _finding(
                "info",
                "token_present",
                "DISCORD_BOT_TOKEN is set and has the shape of a bot token.",
                "Run again with --live to verify it against Discord without printing the token.",
            )
        )

    def pick_list(env_name: str, yaml_name: str) -> tuple[list[str], str]:
        if env_name in env and env.get(env_name, "").strip():
            return split_csv(env.get(env_name)), "env"
        yaml_value = discord_cfg.get(yaml_name)
        items = _as_list(yaml_value)
        if items:
            return items, "config.yaml"
        return [], "unset"

    users, users_src = pick_list("DISCORD_ALLOWED_USERS", "allowed_users")
    roles, roles_src = pick_list("DISCORD_ALLOWED_ROLES", "allowed_roles")
    channels, channels_src = pick_list("DISCORD_ALLOWED_CHANNELS", "allowed_channels")

    allow_all = parse_bool(env.get("DISCORD_ALLOW_ALL_USERS"))
    if allow_all is None and "allow_all_users" in discord_cfg:
        allow_all = parse_bool(str(discord_cfg.get("allow_all_users")))
    gateway_all = parse_bool(env.get("GATEWAY_ALLOW_ALL_USERS"))

    policy = bool(users or roles or channels or allow_all or gateway_all)
    if not policy:
        findings.append(
            _finding(
                "error",
                "no_access_policy",
                "No Discord access policy is configured. Hermes connects and then denies every inbound user.",
                "Set DISCORD_ALLOWED_USERS or DISCORD_ALLOWED_ROLES to numeric IDs. Use DISCORD_ALLOW_ALL_USERS=true only on a private server.",
            )
        )
    else:
        parts = []
        if users:
            parts.append(f"{len(users)} user entr{'y' if len(users) == 1 else 'ies'} ({users_src})")
        if roles:
            parts.append(f"{len(roles)} role entr{'y' if len(roles) == 1 else 'ies'} ({roles_src})")
        if channels:
            parts.append(f"{len(channels)} channel entr{'y' if len(channels) == 1 else 'ies'} ({channels_src})")
        if allow_all:
            parts.append("DISCORD_ALLOW_ALL_USERS")
        if gateway_all:
            parts.append("GATEWAY_ALLOW_ALL_USERS")
        findings.append(
            _finding(
                "info",
                "access_policy_present",
                "An access policy is set: " + ", ".join(parts) + ".",
                "Restart the gateway after any change so the running process reloads it.",
            )
        )

    findings.extend(classify_allowlist("DISCORD_ALLOWED_USERS", users))
    findings.extend(classify_allowlist("DISCORD_ALLOWED_ROLES", roles))
    findings.extend(classify_allowlist("DISCORD_ALLOWED_CHANNELS", channels))

    if allow_all or gateway_all:
        findings.append(
            _finding(
                "warn",
                "allow_all_users",
                "An allow-all flag is on. Every Discord user who can reach the bot can use its tools.",
                "Prefer DISCORD_ALLOWED_USERS or DISCORD_ALLOWED_ROLES. Leave GATEWAY_ALLOW_ALL_USERS off unless every connected platform should be open.",
            )
        )

    if roles or any(not SNOWFLAKE.match(entry) for entry in users):
        findings.append(
            _finding(
                "info",
                "members_intent_required",
                "This policy needs Server Members Intent as well as Message Content Intent.",
                "In the Developer Portal, open Bot, Privileged Gateway Intents, and enable Server Members Intent. Hermes always requires Message Content Intent too.",
            )
        )

    if log_text:
        redacted_log = redact(log_text, secrets)
        for code, pattern in LOG_MARKERS:
            match = pattern.search(redacted_log)
            if not match:
                continue
            excerpt = redacted_log[max(0, match.start() - 60) : match.end() + 60].replace("\n", " ").strip()
            if code == "privileged_intents_rejected":
                findings.append(
                    _finding(
                        "error",
                        code,
                        "gateway.log shows Discord rejected the connection for privileged intents. " + excerpt,
                        "Enable Message Content Intent. Also enable Server Members Intent when the allowlist uses usernames or DISCORD_ALLOWED_ROLES. Save, then `hermes gateway restart`.",
                    )
                )
            elif code == "no_access_policy_logged":
                level = "info" if policy else "error"
                message = (
                    "gateway.log still records a missing access policy, but the current files have one. The running process is stale."
                    if policy
                    else "gateway.log records that inbound Discord messages are denied because no access policy was loaded."
                )
                fix = (
                    "Restart with `hermes gateway restart` after confirming the policy above."
                    if policy
                    else "Set an allowlist, then restart the gateway."
                )
                findings.append(_finding(level, code, message, fix))
            else:
                findings.append(
                    _finding(
                        "error",
                        code,
                        "gateway.log shows Discord rejected the bot token. " + excerpt,
                        "Reset the token in the Developer Portal, update DISCORD_BOT_TOKEN, and restart the gateway.",
                    )
                )
    return findings


def discord_get(path: str, token: str, proxy: str | None, timeout: float = 10) -> tuple[int | None, dict[str, Any]]:
    request = urllib.request.Request(
        API_BASE + path,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "discord-gateway-doctor/0.1.0",
            "Accept": "application/json",
        },
        method="GET",
    )
    handlers: list[Any] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
            if not isinstance(payload, dict):
                return response.status, {}
            return response.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read(4096).decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"message": raw[:180]}
        if not isinstance(payload, dict):
            payload = {}
        return exc.code, payload
    except urllib.error.URLError as exc:
        return None, {"message": str(exc.reason)}


def analyze_live(env: dict[str, str], findings: list[dict[str, str]]) -> list[dict[str, str]]:
    token = env.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        return findings
    proxy = env.get("DISCORD_PROXY", "").strip() or None
    status, payload = discord_get("/users/@me", token, proxy)
    if status is None:
        findings.append(
            _finding(
                "warn",
                "discord_unreachable",
                "The live Discord check did not connect: " + redact(str(payload.get("message", "")), [token]),
                "Retry when this machine can reach discord.com, or set DISCORD_PROXY if the gateway already uses one.",
            )
        )
        return findings
    if status == 401:
        findings.append(
            _finding(
                "error",
                "token_rejected",
                "Discord rejected DISCORD_BOT_TOKEN.",
                "Reset the bot token in the Developer Portal and update the local value. A user token will not work.",
            )
        )
        return findings
    if status != 200:
        message = redact(str(payload.get("message", status)), [token])
        findings.append(
            _finding(
                "warn",
                "discord_unexpected",
                f"Discord /users/@me returned HTTP {status}: {message}",
                "Confirm the token is a bot token and that this host is allowed to call discord.com.",
            )
        )
        return findings

    username = str(payload.get("username") or "")
    bot_id = str(payload.get("id") or "")
    findings.append(
        _finding(
            "info",
            "token_valid",
            f"Discord accepted the token for bot {username} ({bot_id}).",
            "No local change is required for the token itself.",
        )
    )
    embedded = bot_id_from_token(token)
    if embedded and bot_id and embedded != bot_id:
        findings.append(
            _finding(
                "warn",
                "token_id_mismatch",
                "The token's embedded id does not match /users/@me.",
                "Replace DISCORD_BOT_TOKEN with the current token from the same application.",
            )
        )

    app_status, app = discord_get("/applications/@me", token, proxy)
    if app_status != 200:
        findings.append(
            _finding(
                "warn",
                "application_unreadable",
                f"Discord /applications/@me returned HTTP {app_status}. Intent flags were not checked.",
                "The token works for the bot user, but the application lookup failed. Check it in the Developer Portal.",
            )
        )
        return findings

    flags = int(app.get("flags") or 0)
    content_on = bool(flags & (FLAG_MESSAGE_CONTENT | FLAG_MESSAGE_CONTENT_LIMITED))
    members_on = bool(flags & (FLAG_GUILD_MEMBERS | FLAG_GUILD_MEMBERS_LIMITED))
    if not content_on:
        findings.append(
            _finding(
                "error",
                "message_content_intent_off",
                "Message Content Intent is off, so Discord will refuse the gateway connection.",
                "Developer Portal → Bot → Privileged Gateway Intents → enable Message Content Intent → Save Changes → `hermes gateway restart`.",
            )
        )
    else:
        findings.append(
            _finding(
                "info",
                "message_content_intent_on",
                "Message Content Intent is enabled on the application.",
                "If the gateway is still offline, restart it after the portal save.",
            )
        )
    needs_members = any(item["code"] == "members_intent_required" for item in findings)
    if needs_members and not members_on:
        findings.append(
            _finding(
                "error",
                "server_members_intent_off",
                "Server Members Intent is off, but the allowlist needs it.",
                "Enable Server Members Intent beside Message Content Intent, save, and restart the gateway.",
            )
        )
    elif needs_members:
        findings.append(
            _finding(
                "info",
                "server_members_intent_on",
                "Server Members Intent is enabled.",
                "Username entries still only match real usernames, not display names.",
            )
        )
    return findings


def load_home(home: Path) -> tuple[dict[str, str], dict[str, Any], str]:
    env_path = home / ".env"
    config_path = home / "config.yaml"
    log_path = home / "logs" / "gateway.log"
    env: dict[str, str] = {}
    if env_path.is_file():
        env = parse_env(env_path.read_text(encoding="utf-8"))
    discord_cfg: dict[str, Any] = {}
    if config_path.is_file():
        discord_cfg = parse_discord_block(config_path.read_text(encoding="utf-8"))
    log_text = ""
    if log_path.is_file():
        raw = log_path.read_bytes()
        log_text = raw[-200_000:].decode("utf-8", "replace")
    return env, discord_cfg, log_text


def status_of(findings: list[dict[str, str]]) -> str:
    levels = {item["level"] for item in findings}
    if "error" in levels:
        return "error"
    if "warn" in levels:
        return "warn"
    return "ok"


def diagnose(home: Path, live: bool = False) -> dict[str, Any]:
    if not home.is_dir():
        findings = [
            _finding(
                "error",
                "missing_hermes_home",
                f"No Hermes home at {home}.",
                "Pass --hermes-home, or install Hermes so the default ~/.hermes directory exists.",
            )
        ]
        return {"status": "error", "hermes_home": str(home), "findings": findings}
    env, discord_cfg, log_text = load_home(home)
    findings = analyze_config(env, discord_cfg, log_text)
    if live:
        findings = analyze_live(env, findings)
    return {"status": status_of(findings), "hermes_home": str(home), "findings": findings}


def format_text(report: dict[str, Any]) -> str:
    lines = [f"status: {report['status']}", f"hermes_home: {report['hermes_home']}", ""]
    for item in report["findings"]:
        lines.append(f"{item['level']}  {item['code']}")
        lines.append(f"  {item['message']}")
        lines.append(f"  fix: {item['fix']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def exit_code(status: str) -> int:
    return {"ok": 0, "warn": 1, "error": 2}[status]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose a Hermes Discord gateway configuration.")
    parser.add_argument("--hermes-home", default=str(Path.home() / ".hermes"))
    parser.add_argument("--live", action="store_true", help="Verify the token and intent flags with Discord.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    args = parser.parse_args(argv)
    report = diagnose(Path(args.hermes_home).expanduser(), live=args.live)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_text(report), end="")
    return exit_code(report["status"])


if __name__ == "__main__":
    sys.exit(main())
