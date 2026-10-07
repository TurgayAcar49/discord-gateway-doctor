#!/usr/bin/env python3
"""Render a Discord preview from a real doctor report. Text comes from the tool."""

from __future__ import annotations

import importlib.util
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "devops" / "discord-gateway-doctor" / "scripts" / "doctor.py"
OUT = ROOT / "assets" / "discord-preview.png"

spec = importlib.util.spec_from_file_location("discord_gateway_doctor", SCRIPT)
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)

TOKEN = ("M" * 24) + "." + ("C" * 6) + "." + ("B" * 27)

W = 1280
BG = (15, 17, 21)
CARD = (22, 24, 29)
LINE = (42, 45, 53)
TEXT = (215, 218, 224)
MUTED = (139, 145, 154)
ERROR = (240, 113, 120)
WARN = (230, 192, 120)
INFO = (127, 219, 202)
ACCENT = (126, 182, 255)

FONT = "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf"


def sample_report() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "logs").mkdir()
        (home / ".env").write_text(f"DISCORD_BOT_TOKEN={TOKEN}\n", encoding="utf-8")
        (home / "logs" / "gateway.log").write_text(
            "Discord rejected the connection because privileged Gateway Intents are not enabled\n",
            encoding="utf-8",
        )
        return doctor.diagnose(home)


def wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width) or [""]


def main() -> None:
    report = sample_report()
    title = ImageFont.truetype(FONT_BOLD, 28)
    small = ImageFont.truetype(FONT, 18)
    body = ImageFont.truetype(FONT, 20)
    label = ImageFont.truetype(FONT_BOLD, 20)

    lines = 0
    for item in report["findings"]:
        lines += 1 + len(wrap(item["message"], 78))
    height = 320 + lines * 32
    image = Image.new("RGB", (W, height), BG)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((36, 28, W - 36, height - 28), radius=18, fill=CARD, outline=LINE, width=2)
    draw.text((64, 52), "discord-gateway-doctor", font=title, fill=ACCENT)
    draw.text((64, 92), "python doctor.py", font=small, fill=MUTED)

    y = 140
    status_color = {"error": ERROR, "warn": WARN, "ok": INFO}[report["status"]]
    draw.text((64, y), f"status: {report['status']}", font=label, fill=status_color)
    y += 36
    draw.text((64, y), "hermes_home: ~/.hermes", font=body, fill=MUTED)
    y += 48

    colors = {"error": ERROR, "warn": WARN, "info": INFO}
    for item in report["findings"]:
        color = colors[item["level"]]
        draw.text((64, y), f"{item['level']}  {item['code']}", font=label, fill=color)
        y += 30
        for line in wrap(item["message"], 78):
            draw.text((96, y), line, font=body, fill=TEXT)
            y += 28
        y += 16

    draw.text((64, height - 68), "github.com/TurgayAcar49/discord-gateway-doctor", font=small, fill=MUTED)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, "PNG")
    print(OUT)


if __name__ == "__main__":
    main()
