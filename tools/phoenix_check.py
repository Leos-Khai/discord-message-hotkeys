#!/usr/bin/env python3
"""Check the running Phoenix client against what the add-on expects.

The same checks as NVDA+Ctrl+Shift+F11, run from a terminal without NVDA:

    pip install comtypes
    python tools/phoenix_check.py            # report on the open screen
    python tools/phoenix_check.py --lines    # also print the browse mode document

Open a channel or DM first to include the conversation checks, and show the
member list to include those. Exit status is 1 if any check fails.
"""
import argparse
import ctypes
import os
import sys

sys.coinit_flags = 0  # multithreaded apartment, as NVDA's UIA thread uses

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "addon", "appModules"))

import _phoenixBuffer as pb  # noqa: E402
import _phoenixChecks as pc  # noqa: E402


def fetch(hwnd):
    import comtypes
    import comtypes.client
    uia = comtypes.client.GetModule("UIAutomationCore.dll")
    client = comtypes.CoCreateInstance(uia.CUIAutomation8._reg_clsid_, interface=uia.IUIAutomation,
                                       clsctx=comtypes.CLSCTX_INPROC_SERVER)
    request = client.CreateCacheRequest()
    pb.addCacheProperties(request)
    request.TreeScope = pb.TREE_SCOPE_SUBTREE
    request.TreeFilter = client.RawViewCondition
    return pb.rawTreeFromCachedElement(client.ElementFromHandleBuildCache(hwnd, request))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lines", action="store_true", help="print the browse mode document too")
    args = parser.parse_args()
    hwnd = ctypes.windll.user32.FindWindowW(pc.WINDOW_CLASS, None)
    if not hwnd:
        print("No %s window: is the new Discord client running?" % pc.WINDOW_CLASS)
        return 2
    raw = fetch(hwnd)
    buf = pb.build(raw)
    checks = pc.runChecks(raw, pc.WINDOW_CLASS, buf)
    print(pc.report(checks, "Discord Phoenix self-check - %s" % raw.name))
    if args.lines:
        print("\n--- browse mode document ---")
        for i, start in enumerate(buf.lineStarts):
            end = buf.lineStarts[i + 1] if i + 1 < len(buf.lineStarts) else len(buf.text)
            fields = " > ".join(n.role + ("[%s]" % n.landmark if n.landmark else "")
                                for n in buf.fieldChain(start)[-3:])
            print("%4d %-70s | %s" % (i, buf.text[start:end].rstrip("\n")[:70], fields))
    return 1 if any(c.status == pc.FAIL for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
