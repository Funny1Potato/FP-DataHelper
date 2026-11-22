"""Install the FP-DataHelper skill for an agent that runs local terminal commands."""

import argparse
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


APP_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "fp-datahelper"
SKILL_SOURCE = APP_ROOT / "skills" / SKILL_NAME


def install(skills_dir):
    destination = (skills_dir.expanduser() / SKILL_NAME).resolve()
    if destination == SKILL_SOURCE.resolve():
        raise ValueError("Choose your agent's skills directory outside the FP-DataHelper source skill directory.")
    if not (APP_ROOT / "fp_datahelper_cli.py").is_file() or not (APP_ROOT / "Methods").is_dir():
        raise ValueError("Run this installer from a complete FP-DataHelper checkout or package.")

    instructions = (SKILL_SOURCE / "SKILL.md").read_bytes()
    embedded = APP_ROOT / "python-3.10.11-embed-amd64" / "python.exe"
    python = embedded if os.name == "nt" and embedded.is_file() else Path(sys.executable)
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".install-", dir=destination) as temporary:
        staging = Path(temporary)
        (staging / "app-path.txt").write_text(f"{APP_ROOT}\n", encoding="utf-8")
        (staging / "python-path.txt").write_text(f"{python}\n", encoding="utf-8")
        (staging / "SKILL.md").write_bytes(instructions)
        for filename in ("app-path.txt", "python-path.txt", "SKILL.md"):
            (staging / filename).replace(destination / filename)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, required=True,
                        help="The skills directory read by your agent (parent of fp-datahelper).")
    args = parser.parse_args()
    try:
        destination = install(args.skills_dir)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Installation failed: {error}\n")
    print(f"Installed {SKILL_NAME} in {destination}")


if __name__ == "__main__":
    main()
