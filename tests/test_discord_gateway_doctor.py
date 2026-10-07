import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "devops" / "discord-gateway-doctor" / "scripts" / "doctor.py"
SKILL = ROOT / "skills" / "devops" / "discord-gateway-doctor" / "SKILL.md"

spec = importlib.util.spec_from_file_location("discord_gateway_doctor", SCRIPT)
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


TOKEN = ("M" * 24) + "." + ("C" * 6) + "." + ("B" * 27)


def write_home(home: Path, env: str, config: str = "", log: str = "") -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / ".env").write_text(env, encoding="utf-8")
    if config:
        (home / "config.yaml").write_text(config, encoding="utf-8")
    if log:
        log_dir = home / "logs"
        log_dir.mkdir(exist_ok=True)
        (log_dir / "gateway.log").write_text(log, encoding="utf-8")


def codes(report: dict) -> dict[str, str]:
    return {item["code"]: item["level"] for item in report["findings"]}


class DoctorTests(unittest.TestCase):
    def test_skill_frontmatter_is_loadable(self):
        content = SKILL.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        end = content.index("\n---\n", 3)
        frontmatter = content[4:end]
        self.assertIn("name: discord-gateway-doctor", frontmatter)
        description = "Diagnose a silent or offline Hermes Discord gateway."
        self.assertIn(f"description: {description}", frontmatter)
        self.assertLessEqual(len(description), 60)
        self.assertTrue(description.endswith("."))
        self.assertTrue(content[end + len("\n---\n") :].strip())

    def test_missing_home(self):
        report = doctor.diagnose(Path("/tmp/does-not-exist-hermes-doctor"))
        self.assertEqual(report["status"], "error")
        self.assertIn("missing_hermes_home", codes(report))

    def test_fail_closed_without_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(home, f"DISCORD_BOT_TOKEN={TOKEN}\n")
            report = doctor.diagnose(home)
        found = codes(report)
        self.assertEqual(report["status"], "error")
        self.assertEqual(found["no_access_policy"], "error")
        self.assertEqual(found["token_present"], "info")
        self.assertNotIn(TOKEN, json.dumps(report))

    def test_numeric_user_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(
                home,
                f'DISCORD_BOT_TOKEN="{TOKEN}"\nDISCORD_ALLOWED_USERS=284102345871466496\n',
            )
            report = doctor.diagnose(home)
        self.assertEqual(report["status"], "ok")
        self.assertIn("access_policy_present", codes(report))

    def test_username_warns_and_requires_members_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(
                home,
                f"export DISCORD_BOT_TOKEN={TOKEN}\nDISCORD_ALLOWED_USERS=teknium\n",
            )
            report = doctor.diagnose(home)
        found = codes(report)
        self.assertEqual(report["status"], "warn")
        self.assertEqual(found["username_allowlist"], "warn")
        self.assertIn("members_intent_required", found)

    def test_role_names_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(
                home,
                f"DISCORD_BOT_TOKEN={TOKEN}\nDISCORD_ALLOWED_ROLES=Developer, 1149869525567799297\n",
            )
            report = doctor.diagnose(home)
        self.assertEqual(codes(report)["invalid_id_list"], "error")

    def test_yaml_channel_allowlist_counts_as_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(
                home,
                f"DISCORD_BOT_TOKEN={TOKEN}\n",
                "discord:\n  allowed_channels:\n    - \"123456789012345678\"\n",
            )
            report = doctor.diagnose(home)
        self.assertEqual(report["status"], "ok")
        policy = next(item for item in report["findings"] if item["code"] == "access_policy_present")
        self.assertIn("config.yaml", policy["message"])

    def test_allow_all_is_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(
                home,
                f"DISCORD_BOT_TOKEN={TOKEN}\nDISCORD_ALLOW_ALL_USERS=true\n",
            )
            report = doctor.diagnose(home)
        self.assertEqual(report["status"], "warn")
        self.assertIn("allow_all_users", codes(report))

    def test_stale_log_is_info_when_policy_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(
                home,
                f"DISCORD_BOT_TOKEN={TOKEN}\nDISCORD_ALLOWED_USERS=284102345871466496\n",
                log="No Discord access policy configured; inbound Discord messages will be denied by default.\n",
            )
            report = doctor.diagnose(home)
        self.assertEqual(codes(report)["no_access_policy_logged"], "info")
        self.assertEqual(report["status"], "ok")

    def test_privileged_intent_log_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(
                home,
                f"DISCORD_BOT_TOKEN={TOKEN}\nDISCORD_ALLOWED_USERS=284102345871466496\n",
                log="Discord rejected the connection because privileged Gateway Intents are not enabled\n",
            )
            report = doctor.diagnose(home)
        self.assertEqual(codes(report)["privileged_intents_rejected"], "error")

    def test_log_redacts_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(
                home,
                f"DISCORD_BOT_TOKEN={TOKEN}\n",
                log=f"Improper token {TOKEN} has been refused\n",
            )
            report = doctor.diagnose(home)
        blob = json.dumps(report)
        self.assertNotIn(TOKEN, blob)
        self.assertIn("[redacted]", blob)
        self.assertIn("token_rejected_logged", codes(report))

    def test_live_intent_flags(self):
        calls = []

        def fake_get(path, token, proxy, timeout=10):
            calls.append(path)
            if path == "/users/@me":
                return 200, {"id": "123", "username": "hermes"}
            flags = doctor.FLAG_MESSAGE_CONTENT
            return 200, {"flags": flags}

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(
                home,
                f"DISCORD_BOT_TOKEN={TOKEN}\nDISCORD_ALLOWED_ROLES=1149869525567799297\n",
            )
            with patch.object(doctor, "discord_get", fake_get):
                report = doctor.diagnose(home, live=True)
        found = codes(report)
        self.assertEqual(calls, ["/users/@me", "/applications/@me"])
        self.assertIn("token_valid", found)
        self.assertEqual(found["message_content_intent_on"], "info")
        self.assertEqual(found["server_members_intent_off"], "error")
        self.assertNotIn(TOKEN, json.dumps(report))

    def test_cli_json_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(home, f"DISCORD_BOT_TOKEN={TOKEN}\nDISCORD_ALLOWED_USERS=284102345871466496\n")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = doctor.main(["--json", "--hermes-home", str(home)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue())["status"], "ok")


if __name__ == "__main__":
    unittest.main()
