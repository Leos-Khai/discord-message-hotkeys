#!/usr/bin/env python3
"""Visit every kind of Phoenix screen and self-check each one.

After a Discord update, this tells you in one run which screens browse mode
still understands:

    pip install comtypes
    python tools/phoenix_tour.py

It drives the running client the way a user would - opening the Friends tabs,
a DM, a server channel, a forum and one of its posts, Discover, Quests, Shop,
Nitro, Message Requests, Settings and the Inbox - and runs the same checks as
NVDA+Ctrl+Shift+F11 on each. It only opens and selects things: it never
types, sends, reacts or changes a setting, and it skips voice and stage
channels (opening one joins it). It does mark the channels it opens as read.
Popups (Settings, Inbox) are closed with Escape. Exit status 1 if any screen
has a failure.
"""
import ctypes
import ctypes.wintypes as wintypes
import os
import sys
import time

sys.coinit_flags = 0  # multithreaded apartment, as NVDA's UIA thread uses

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, "addon", "appModules"))

import _phoenixChecks as pc  # noqa: E402
import phoenix_check  # noqa: E402

import comtypes  # noqa: E402
import comtypes.client  # noqa: E402

UIA = comtypes.client.GetModule("UIAutomationCore.dll")
CLIENT = comtypes.CoCreateInstance(UIA.CUIAutomation8._reg_clsid_, interface=UIA.IUIAutomation,
                                   clsctx=comtypes.CLSCTX_INPROC_SERVER)
USER32 = ctypes.windll.user32
SETTLE = 1.5  # seconds for Discord to show what was opened
INVOKE, SELECT = 10000, 10010  # UIA pattern IDs

# Never press anything whose name contains these, even by accident.
FORBIDDEN = ("log out", "delete", "disable account", "remove", "leave", "block", "report", "close")


def hwnd():
    return USER32.FindWindowW(pc.WINDOW_CLASS, None)


def tree():
    return phoenix_check.fetch(hwnd())


def find(raw, test):
    stack = [raw]
    while stack:
        r = stack.pop()
        if test(r):
            return r
        stack.extend(reversed(r.children))
    return None


def press(test, pattern=INVOKE):
    """Invoke (or select) the first element passing test. True if pressed."""
    target = find(tree(), lambda r: test(r) and (r.hasInvoke if pattern == INVOKE else r.hasSelectionItem))
    if target is None:
        return False
    if any(word in (target.name or "").lower() for word in FORBIDDEN):
        raise RuntimeError("refusing to press %r" % target.name)
    p = target.element.GetCurrentPattern(pattern)
    if pattern == INVOKE:
        p.QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
    else:
        p.QueryInterface(UIA.IUIAutomationSelectionItemPattern).Select()
    time.sleep(SETTLE)
    return True


def named(name):
    return lambda r: (r.name or "") == name


def startswith(prefix):
    return lambda r: (r.name or "").lower().startswith(prefix.lower())


def contains(text):
    return lambda r: text.lower() in (r.name or "").lower()


def focusAndEnter(test):
    """Focus an element and post Enter - for an item Discord counts as selected."""
    target = find(tree(), test)
    if target is None:
        return False
    target.element.SetFocus()
    time.sleep(0.3)
    postKey(0x0D)
    return True


def openItem(test, expect):
    """Select a tree item; if that doesn't reach the screen expected, focus it and press Enter."""
    if press(test, SELECT) and waitFor(expect, timeout=3.0)[1]:
        return True
    return focusAndEnter(test)


def postKey(vk):
    USER32.PostMessageW(hwnd(), 0x100, vk, 0x00010001)
    USER32.PostMessageW(hwnd(), 0x101, vk, 0xC0010001)
    time.sleep(SETTLE)


def postClick(test):
    """A left click posted to the centre of an element; the pointer doesn't move."""
    target = find(tree(), test)
    if target is None:
        return False
    r = target.element.CurrentBoundingRectangle
    pt = wintypes.POINT((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    USER32.ScreenToClient(hwnd(), ctypes.byref(pt))
    lp = ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)
    for msg, w in ((0x0200, 0), (0x0201, 1), (0x0202, 0)):
        USER32.PostMessageW(hwnd(), msg, w, lp)
        time.sleep(0.05)
    time.sleep(SETTLE)
    return True


def firstChannel(kind):
    """The first channel of a kind ("text", "forum", "announcement") in any server."""
    raw = tree()
    sidebar = find(raw, named("Servers sidebar"))
    servers = []
    stack = [sidebar] if sidebar else []
    while stack:
        r = stack.pop()
        if r.controlType == 50024 and r.hasSelectionItem and "folder" not in (r.name or "").lower() \
                and r.name not in ("Direct Messages", "Add a Server", "Discover"):
            servers.append(r.name)
        stack.extend(r.children)
    for server in servers:
        press(named(server), SELECT)
        channel = find(tree(), lambda r: r.controlType == 50005 and "(%s channel)" % kind in (r.name or ""))
        if channel is not None:
            return channel.name
    return None


def waitFor(expect, timeout=6.0):
    """Wait until the screen is the one expected (a kind, or a test on the tree)."""
    deadline = time.time() + timeout
    while True:
        raw = tree()
        ok = expect(raw) if callable(expect) else pc.detectScreen(raw).kind == expect
        if ok or time.time() > deadline:
            return raw, ok
        time.sleep(0.4)


def hasThread(raw):
    return pc.detectScreen(raw).thread is not None


def checkHere(results, label, expect=None):
    raw, ok = waitFor(expect) if expect is not None else (tree(), True)
    if not ok:
        print("%-28s didn't open (expected %s); checking what is shown" % (label, expect))
    checks = pc.runChecks(raw, pc.WINDOW_CLASS)
    failed = [c for c in checks if c.status == pc.FAIL]
    results.append((label, pc.screenOf(checks), checks))
    print("%-28s %-22s %s" % (label, pc.screenOf(checks), pc.spokenSummary(checks).split(": ", 1)[-1]))
    for c in failed:
        print("    FAIL %s - %s" % (c.name, c.detail))


def tour():
    results = []

    def home():
        # The DM list (Friends, DMs, Shop...) only shows under Direct Messages.
        press(named("Direct Messages"), SELECT)
        waitFor(lambda raw: find(raw, lambda r: r.controlType == 50005 and startswith("Friends")(r)) is not None)
        return True

    def friendsLink():
        return press(lambda r: r.controlType == 50005 and startswith("Friends")(r), INVOKE)

    steps = [
        ("Friends: Online", "friends", lambda: home() and friendsLink() and press(named("Online"), SELECT)),
        ("Friends: All", "friends", lambda: press(named("All"), SELECT)),
        ("Friends: Pending", "friends", lambda: press(startswith("Pending"), SELECT)),
        ("Friends: Add Friend", "friends", lambda: press(named("Add Friend"), SELECT)),
        ("Direct message", "dm", lambda: press(contains("(direct message)"), INVOKE)),
        ("Group DM", "groupDm", lambda: press(contains("(group message)"), INVOKE)),
        ("Message Requests", "messageRequests", lambda: press(named("Message Requests"), INVOKE)),
        ("Shop", "shop", lambda: press(named("Shop"), INVOKE)),
        ("Quests", "quests", lambda: press(named("Quests"), INVOKE)),
        ("Nitro", "nitro", lambda: press(named("Nitro Home"), INVOKE)),
        ("Discover", "discover", lambda: openItem(named("Discover"), "discover")),
    ]
    for label, expect, go in steps:
        if go():
            checkHere(results, label, expect)
        else:
            print("%-28s skipped: couldn't open it" % label)
    for kind, expect in (("text", "channel"), ("announcement", "announcement"), ("forum", "forum")):
        name = firstChannel(kind)
        if name and press(named(name), INVOKE):
            checkHere(results, "Server %s channel" % kind, expect)
            if kind == "forum":
                # Discord ignores a press on the post it opened last, so try
                # each post in turn until a thread panel opens.
                posts = []
                stack = [tree()]
                while stack:
                    r = stack.pop()
                    if r.controlType == 50000 and r.hasInvoke and (r.name or "").startswith("Post "):
                        posts.append(r.name)
                    stack.extend(r.children)
                for post in posts[:4]:
                    if press(named(post), INVOKE) and waitFor(hasThread, timeout=3.0)[1]:
                        checkHere(results, "Forum post (thread)", hasThread)
                        break
                else:
                    print("%-28s skipped: no post opened a thread" % "Forum post (thread)")
        else:
            print("%-28s skipped: no %s channel in your servers" % ("Server %s channel" % kind, kind))
    if press(named("User Settings"), INVOKE):
        checkHere(results, "Settings", "settings")
        postKey(0x1B)
    if postClick(named("Inbox")):
        checkHere(results, "Inbox", "inbox")
        postKey(0x1B)
    return results


def main():
    if not hwnd():
        print("No %s window: is the new Discord client running?" % pc.WINDOW_CLASS)
        return 2
    results = tour()
    bad = [label for label, _, checks in results if any(c.status == pc.FAIL for c in checks)]
    print("\n%d screens checked, %d with failures%s" % (len(results), len(bad), (": " + ", ".join(bad)) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
