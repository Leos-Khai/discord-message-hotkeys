#!/usr/bin/env python3
"""Build the NVDA add-on package.

An .nvda-addon file is just a ZIP whose ROOT contains manifest.ini plus the
plugin folders (here: appModules/). Run:

    python build.py

Output: dist/discordMessageHotkeys-<version>.nvda-addon
"""
import os
import re
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.join(HERE, "addon")
DIST_DIR = os.path.join(HERE, "dist")


def read_version():
    manifest = os.path.join(ADDON_DIR, "manifest.ini")
    with open(manifest, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"\s*version\s*=\s*(.+)", line)
            if m:
                return m.group(1).strip().strip('"')
    return "0.0.0"


def main():
    version = read_version()
    os.makedirs(DIST_DIR, exist_ok=True)
    out = os.path.join(DIST_DIR, "discordMessageHotkeys-v%s.nvda-addon" % version)
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _, files in os.walk(ADDON_DIR):
            if "__pycache__" in dirpath:
                continue
            for name in files:
                if name.endswith(".pyc"):
                    continue
                full = os.path.join(dirpath, name)
                arc = os.path.relpath(full, ADDON_DIR)  # manifest.ini at root
                z.write(full, arc)
    print("Built:", out)


if __name__ == "__main__":
    main()
