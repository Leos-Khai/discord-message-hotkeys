#!/usr/bin/env python3
"""Extract one version's section from CHANGELOG.md.

    python scripts/changelog.py 0.6.1

Prints the body of the "## [0.6.1] - ..." section to stdout, stopping at the
next "## " heading. Exits 1 if the version has no section, which is what makes
the release workflow fail loudly instead of publishing empty notes.

Standard library only, to match build.py -- this repo has no build deps.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG = os.path.join(HERE, "CHANGELOG.md")


def extract(version, text):
    # Matches "## [0.6.1] - 2026-07-19" and the bare "## 0.6.1" form.
    start = re.compile(r"^##\s+\[?" + re.escape(version) + r"\]?(\s|$)")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if start.match(line):
            body = []
            for later in lines[i + 1:]:
                if later.startswith("## "):
                    break
                body.append(later)
            return "\n".join(body).strip()
    return None


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: changelog.py <version>")
    version = sys.argv[1]
    with open(CHANGELOG, "r", encoding="utf-8") as f:
        section = extract(version, f.read())
    if not section:
        sys.exit(
            "No CHANGELOG.md section for version %s.\n"
            "Add a '## [%s] - <date>' entry describing the release, then retry."
            % (version, version)
        )
    print(section)


if __name__ == "__main__":
    main()
