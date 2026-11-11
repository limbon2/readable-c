"""Checks the skill's package files: metadata, versions, links and dependency pins."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_FOLDER = ROOT / "skills" / "readable-c"
MAX_SKILL_LINES = 300
MAX_DESCRIPTION = 1024


def frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if match is None:
        raise SystemExit("SKILL.md must begin with YAML front matter")
    block = match.group(1)
    name = re.search(r"(?m)^name:\s*(\S+)\s*$", block)
    version = re.search(r'(?m)^\s+version:\s*"?([0-9]+\.[0-9]+\.[0-9]+)"?\s*$', block)
    description = re.search(r"(?ms)^description:\s*>-?\n(.*?)(?=^\S)", block + "\nend:")
    if name is None or version is None or description is None:
        raise SystemExit("SKILL.md front matter needs name, description and metadata.version")
    folded = " ".join(line.strip() for line in description.group(1).splitlines())
    return {"name": name.group(1), "version": version.group(1), "description": folded}


def pins_of_script(text: str) -> set[str]:
    block = re.search(r"(?ms)^# /// script\n(.*?)^# ///", text)
    if block is None:
        raise SystemExit("readable_c.py needs a PEP 723 block")
    return set(re.findall(r'#\s+"([^"]+)"', block.group(1)))


def pins_of_pyproject(text: str) -> set[str]:
    group = re.search(r"(?ms)^dev = \[\n(.*?)^\]", text)
    if group is None:
        raise SystemExit("pyproject.toml needs a dev dependency group")
    return set(re.findall(r'"([^"]+)"', group.group(1)))


def main() -> int:
    problems = []
    skill_text = (SKILL_FOLDER / "SKILL.md").read_text(encoding="utf-8")
    meta = frontmatter(skill_text)
    if meta["name"] != SKILL_FOLDER.name:
        problems.append(
            f"the skill's name `{meta['name']}` must equal its folder `{SKILL_FOLDER.name}`"
        )
    if len(meta["description"]) > MAX_DESCRIPTION:
        problems.append(
            f"the description has {len(meta['description'])} characters; the limit is {MAX_DESCRIPTION}"
        )
    if skill_text.count("\n") > MAX_SKILL_LINES:
        problems.append(
            f"SKILL.md is longer than {MAX_SKILL_LINES} lines; move detail into references/"
        )

    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    released = re.search(r"(?m)^## \[([0-9]+\.[0-9]+\.[0-9]+)\]", changelog)
    versions = {
        "SKILL.md": meta["version"],
        "plugin.json": plugin.get("version"),
        "CHANGELOG.md": released.group(1) if released else None,
    }
    if len(set(versions.values())) != 1:
        problems.append(f"the versions disagree: {versions}")
    plugin_names = [entry.get("name") for entry in marketplace.get("plugins", [])]
    if plugin.get("name") not in plugin_names:
        problems.append("marketplace.json must list the plugin by the name in plugin.json")

    for link in re.findall(r"\]\(((?:references|scripts)/[^)#]+)", skill_text):
        if not (SKILL_FOLDER / link).exists():
            problems.append(f"SKILL.md links to {link}, which does not exist")

    script_pins = pins_of_script(
        (SKILL_FOLDER / "scripts" / "readable_c.py").read_text(encoding="utf-8")
    )
    dev_pins = pins_of_pyproject((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    missing = script_pins - dev_pins
    if missing:
        problems.append(f"pyproject.toml's dev group lacks the tool's pins: {sorted(missing)}")

    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"validate_package: readable-c {meta['version']} is consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
