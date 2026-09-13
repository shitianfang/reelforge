"""Prompt recipes encoding the researched rules for high-impact visuals.

Sources distilled here (see README for links):
- Hailuo visual-contrast guide: subject-first ordering, one hard light source,
  chromatic contrast in plain color words, lens terms to mask noise, identical
  5-7 word subject anchor across a sequence.
- Viral POV format teardowns: never say "POV camera"; state where the camera
  is physically mounted; always forbid burned-in subtitles.
"""

import re
from dataclasses import dataclass

# Vague words the research flags as actively harmful; lint rejects them.
# Matched on word boundaries: "cool teal" (a color temperature) must not trip.
BANNED = ["soft lighting", "moody", "nice", "beautiful", "cinematic vibes"]

STYLES = {
    "contrast-noir": {
        # "hard top-down spotlight" read as headwear: models kept adding hard hats
        "light": "a single harsh spotlight from directly above, high-contrast noir shadows, deep black background",
        "color": "warm orange subject against a cool teal background",
        "lens": "35mm lens, shallow depth of field",
    },
    "rim-glow": {
        "light": "sharp rim lighting from the rear creating a glowing outline, deep shadows behind",
        "color": "cold blue background, warm gold edge light on the subject",
        "lens": "85mm macro shot, shallow depth of field",
    },
    "neon-street": {
        "light": "hard neon signs as the only light source, wet asphalt reflections",
        "color": "magenta and cyan neon against near-black streets",
        "lens": "24mm lens, low angle",
    },
    "pov-pet": {
        "light": "natural daylight, slight lens flare",
        "color": "high color contrast between foreground and background",
        "lens": "ultra-wide fisheye action camera, motion blur, shaky handheld footage",
        "mount": "action camera strapped to the animal's chest harness (that is where the camera is)",
    },
    "pov-vlog": {
        "light": "natural light, casual handheld feel",
        "color": "subject clearly separated from the background",
        "lens": "wide selfie lens, 4K action camera look",
        "mount": "holding a selfie stick (that is where the camera is)",
    },
}

SUFFIX = "no subtitles, no on-screen text, no watermark"


@dataclass
class ShotBrief:
    subject: str  # the anchor: keep it identical across a sequence, 5-7 words
    action: str
    scene: str = ""


def _style(name: str) -> dict:
    if name not in STYLES:
        raise KeyError(f"unknown style '{name}'; available: {', '.join(STYLES)}")
    return STYLES[name]


def image_prompt(brief: ShotBrief, style: str) -> str:
    s = _style(style)
    parts = [brief.subject]
    if "mount" in s:
        parts.append(f"first-person view, {s['mount']}")
    parts += [s["light"], s["color"], brief.scene, s["lens"], "8k still frame", SUFFIX]
    return ", ".join(p for p in parts if p)


def video_prompt(brief: ShotBrief, style: str, on_drop: bool = False) -> str:
    s = _style(style)
    motion = "fast push-in, action peak on the final beat" if on_drop else "steady tracking shot"
    parts = [brief.subject, brief.action]
    if "mount" in s:
        parts.append(f"first-person view, {s['mount']}")
    parts += [s["light"], s["color"], brief.scene, s["lens"], motion, SUFFIX]
    return ", ".join(p for p in parts if p)


def lint(prompt: str) -> list[str]:
    low = prompt.lower()
    return [w for w in BANNED if re.search(rf"\b{re.escape(w)}\b", low)]
