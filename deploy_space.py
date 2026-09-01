"""Copy the runtime files into a Hugging Face Space checkout and (optionally) push.

WHY THIS EXISTS. A Space reads its configuration -- SDK, app file, python version --
from YAML front matter in README.md at its repo root, and there is no way to configure
one without it. This repo's README.md is the project's permanent record: 1,500+ lines
of results, design decisions and gotchas. Pasting front matter on top of that would
make the Space's landing page the entire engineering record, which is the wrong first
screen for someone who arrived to click a demo.

Most projects do exactly that anyway, and it is a respectable choice. This one keeps a
separate short card (Docs/SPACE_README.md) and copies it into place at deploy time, so
neither README has to compromise and the two repos never fight over the same file.

USAGE

    python deploy_space.py                      # sync files, show what changed
    python deploy_space.py --commit             # ... and commit in the Space checkout
    python deploy_space.py --commit --push      # ... and push it live

First time, clone the Space beside the repo (it is gitignored):

    git clone https://huggingface.co/spaces/<user>/<space> .space

Pushing is deliberately behind a flag. Everything up to `--push` is local and
reversible; `--push` publishes.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
DEFAULT_TARGET = REPO / ".space"

# What the deployed app actually needs. Deliberately explicit rather than "everything
# except X": a deploy set that is a denylist grows silently, and the whole point is to
# know what is being published.
#
# eval/ is NOT optional. app.py imports question_set_fingerprint and GOLDEN from
# eval.run_eval, and reads eval/results/*.json to show each retrieval mode's measured
# figures -- so the harness and the committed results ship with the app.
DIRS = ["src", "eval", "config", "chroma"]
FILES = ["app.py"]

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache")

# The Space installs from requirements.txt and nothing else, so the lockfile has to
# ARRIVE under that name. Shipping the 111-package closure rather than the 9 direct
# pins is the reproducible choice: those four transitively-resolved packages were
# measured as immaterial to retrieval, and this is what keeps them that way.
REQUIREMENTS_SOURCE = "requirements-lock.txt"

CARD = "Docs/SPACE_README.md"


def run(args, cwd, check=True):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)


def sync(target):
    copied = []
    for name in DIRS:
        src, dst = REPO / name, target / name
        if not src.is_dir():
            sys.exit(f"missing directory: {src}")
        # Removed first, so a file deleted here is deleted there. Without this the
        # Space accumulates files the repo no longer has, which is how a deploy
        # starts differing from its source in ways nobody can see.
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=IGNORE)
        copied.append(name + "/")

    for name in FILES:
        shutil.copy2(REPO / name, target / name)
        copied.append(name)

    shutil.copy2(REPO / REQUIREMENTS_SOURCE, target / "requirements.txt")
    copied.append(f"{REQUIREMENTS_SOURCE} -> requirements.txt")

    shutil.copy2(REPO / CARD, target / "README.md")
    copied.append(f"{CARD} -> README.md")
    return copied


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default=str(DEFAULT_TARGET),
                    help="the Space checkout (default: .space)")
    ap.add_argument("--commit", action="store_true", help="commit in the Space checkout")
    ap.add_argument("--push", action="store_true", help="push (implies --commit)")
    ap.add_argument("-m", "--message", default="sync from source repo")
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if not (target / ".git").is_dir():
        sys.exit(
            f"{target} is not a git checkout.\n\n"
            "Clone the Space first:\n"
            "    git clone https://huggingface.co/spaces/<user>/<space> .space\n"
        )

    # A .env in the deploy set would publish live API keys. It is not in DIRS or
    # FILES, so this cannot currently happen -- the check is here because the cost of
    # being wrong is a leaked credential in a public git history, and a deploy set is
    # exactly the kind of list that grows without anyone re-reading it.
    for leak in (".env", ".env.local"):
        if (target / leak).exists():
            sys.exit(f"REFUSING TO CONTINUE: {target / leak} exists. Keys must live in "
                     "the Space's Settings -> Secrets, never in the repo.")

    copied = sync(target)
    print(f"synced into {target}")
    for item in copied:
        print(f"  {item}")

    status = run(["git", "status", "--porcelain"], target).stdout.strip()
    if not status:
        print("\nno changes -- the Space is already up to date")
        return
    print("\nchanges in the Space checkout:")
    for line in status.splitlines()[:40]:
        print(f"  {line}")
    extra = len(status.splitlines()) - 40
    if extra > 0:
        print(f"  ... and {extra} more")

    if not (args.commit or args.push):
        print("\nnothing committed. Re-run with --commit, then --push when ready.")
        return

    run(["git", "add", "-A"], target)
    run(["git", "commit", "-m", args.message], target)
    print(f"\ncommitted in {target}")

    if not args.push:
        print("not pushed. Re-run with --push to publish.")
        return

    print("pushing to the Space...")
    result = run(["git", "push"], target, check=False)
    print(result.stdout or result.stderr)
    if result.returncode != 0:
        sys.exit("push failed -- see above")
    print("pushed. Watch the build log in the Space's UI.")
    print("Reminder: GOOGLE_API_KEY goes in Settings -> Secrets, not in the repo.")


if __name__ == "__main__":
    main()
