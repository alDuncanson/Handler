"""Write the README badges as SVGs: uv run python -m scripts.badges <out-dir>."""

import os
import sys
from pathlib import Path

import httpx
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT

from scripts.badge import badge

STATUS_COLORS = {
    "stable": "brightgreen",
    "mature": "brightgreen",
    "beta": "yellow",
    "inactive": "red",
}


def fetch(url: str, headers: dict[str, str] | None = None) -> dict:
    return (
        httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
        .raise_for_status()
        .json()
    )


def main(out_dir: str) -> None:
    github = {"Accept": "application/vnd.github+json"}
    if token := os.environ.get("GH_TOKEN"):
        github["Authorization"] = f"Bearer {token}"

    pypi = fetch("https://pypi.org/pypi/a2a-handler/json")["info"]
    status = next(
        classifier.rsplit(" - ", 1)[-1].lower()
        for classifier in pypi["classifiers"]
        if classifier.startswith("Development Status ::")
    )
    repo = fetch("https://api.github.com/repos/alDuncanson/Handler", github)

    badges = {
        "pypi-version": badge("pypi", f"v{pypi['version']}", "blue"),
        "pypi-status": badge("status", status, STATUS_COLORS.get(status, "orange")),
        "a2a-protocol": badge("A2A Protocol", f"v{PROTOCOL_VERSION_CURRENT}", "blue"),
        "stars": badge("stars", str(repo["stargazers_count"]), "lightgrey"),
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, svg in badges.items():
        (out / f"{name}.svg").write_text(svg)
    print(f"wrote {', '.join(badges)} to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "badges")
