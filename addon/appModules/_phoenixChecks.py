# -*- coding: utf-8 -*-
# Discord Message Hotkeys - self-check for the Phoenix client's structure.
#
# Browse mode for Phoenix (_phoenixBuffer.py, _phoenixBrowseMode.py) rests on
# what Discord's accessibility tree looks like: the window class, the names of
# its regions, how a message row is built, and so on. Discord changes its UI
# often, and when it does, browse mode degrades quietly - a region stops being
# a landmark, messages lose their headings - rather than failing loudly.
#
# This module lists every one of those assumptions as a check, run against a
# live tree (NVDA+Ctrl+Shift+F11 in Discord, or tools/phoenix_check.py) or a
# recorded one (tests/). Each check passes, fails, warns, or is skipped when
# the screen doesn't have that part (no conversation open, say). Pure Python,
# no NVDA imports.

try:
    from . import _phoenixBuffer as pb
except ImportError:  # loaded on its own, by tests/ or tools/
    import _phoenixBuffer as pb

PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"

WINDOW_CLASS = "Zed::Window"


class Check(object):
    __slots__ = ("name", "status", "detail")

    def __init__(self, name, status, detail=""):
        self.name = name
        self.status = status
        self.detail = detail

    def __repr__(self):
        return "<Check %s %s: %s>" % (self.status, self.name, self.detail)


def _walk(raw):
    stack = [raw]
    while stack:
        r = stack.pop()
        yield r
        stack.extend(reversed(r.children))


def _find(raw, pred):
    for r in _walk(raw):
        if pred(r):
            return r
    return None


def _findAll(raw, pred):
    return [r for r in _walk(raw) if pred(r)]


def _named(controlType, name=None, startswith=None, endswith=None):
    def pred(r):
        if r.controlType != controlType:
            return False
        n = r.name or ""
        if name is not None and n != name:
            return False
        if startswith is not None and not n.lower().startswith(startswith.lower()):
            return False
        if endswith is not None and not n.lower().endswith(endswith.lower()):
            return False
        return True
    return pred


def _isConversation(r):
    lower = (r.name or "").lower()
    return r.controlType == pb.CT_GROUP and (
        (lower.endswith("(channel)") and not lower.startswith("members list for"))
        or lower.startswith("text chat for voice channel"))


def runChecks(raw, windowClass=None, buf=None):
    """Check a fetched Phoenix tree. Returns a list of Check, in report order."""
    out = []

    def add(name, ok, detail="", warnOnly=False):
        out.append(Check(name, PASS if ok else (WARN if warnOnly else FAIL), detail))

    def skip(name, why):
        out.append(Check(name, SKIP, why))

    # -- the window -------------------------------------------------------
    if windowClass is not None:
        add("Window class is %s" % WINDOW_CLASS, windowClass == WINDOW_CLASS,
            "found %r; browse mode only attaches to this class" % windowClass)
    add("Window title ends with 'Discord'", (raw.name or "").endswith("Discord"),
        "title %r; browse mode only attaches to such windows" % raw.name)
    pane = next((c for c in raw.children if c.controlType == pb.CT_PANE), None)
    add("Main pane under the window", pane is not None,
        "the top-level sections are expected as children of one pane")
    if pane is None:
        return out

    # -- regions D moves between -----------------------------------------
    top = [c for c in pane.children]
    add("Top bar: Go back button", any(c.controlType == pb.CT_BUTTON and c.name == "Go back" for c in top),
        "the loose run before the first section is wrapped as the Top bar landmark")
    sidebar = next((c for c in top if c.controlType == pb.CT_GROUP and c.name == "Servers sidebar"), None)
    add("Region 'Servers sidebar'", sidebar is not None, "a navigation landmark, and Ctrl+Shift+S")
    if sidebar is not None:
        tree = _find(sidebar, lambda r: r.controlType == pb.CT_TREE)
        items = _findAll(sidebar, lambda r: r.controlType == pb.CT_TREEITEM)
        add("Server list is a tree of tree items", tree is not None and len(items) > 0,
            "%d tree items" % len(items))
        add("Server items are selectable", any(i.hasSelectionItem for i in items),
            "Enter opens a server by selecting its item", warnOnly=True)
    channelsSide = next((c for c in top if c.controlType == pb.CT_GROUP and c.name
                         and (c.name == "Private channels" or c.name.lower().endswith("(server)"))), None)
    add("Region 'Private channels' or '<server> (server)'", channelsSide is not None,
        "the channel or DM list; a navigation landmark, and Ctrl+Shift+C")
    if channelsSide is not None:
        lst = _find(channelsSide, lambda r: r.controlType == pb.CT_LIST
                    and r.name in ("Direct Messages", "Channels"))
        add("Channel/DM list named 'Direct Messages' or 'Channels'", lst is not None,
            "Ctrl+Shift+C looks for these names")
    user = next((c for c in top if c.controlType == pb.CT_GROUP and c.name == "User status and settings"), None)
    add("Region 'User status and settings'", user is not None, "a region, and Ctrl+Shift+X")

    # -- the conversation ----------------------------------------------------
    conv = next((c for c in top if _isConversation(c)), None)
    if conv is None:
        skip("Conversation checks", "no channel or DM open")
    else:
        add("Conversation named '<name> (channel)'", True, conv.name)
        header = next((c for c in top if c.controlType == pb.CT_GROUP and c.name == "Channel header"), None)
        add("Region 'Channel header'", header is not None, "shown as a region above the conversation",
            warnOnly=True)
        msgs = _find(conv, _named(pb.CT_LIST, startswith="messages"))
        add("Message list named 'Messages in ...'", msgs is not None,
            "Alt+1..0, Alt+D, auto-read and browse mode all find messages by this name")
        if msgs is not None:
            rows = [c for c in msgs.children if c.controlType == pb.CT_LISTITEM]
            add("Message rows are list items", len(rows) > 0, "%d rows loaded" % len(rows))
            bodies = [b for b in _walk(msgs) if pb.isMessageBody(b)]
            add("Message body: focusable grouping 'author , text , time'", len(bodies) > 0,
                "%d of %d rows" % (len(bodies), len(rows)))
            if bodies:
                headed = [b for b in bodies if any(c.controlType == pb.CT_TEXT and c.headingLevel for c in b.children)]
                add("Message header: a heading inside the body", len(headed) > 0,
                    "%d of %d messages start a group with a header" % (len(headed), len(bodies)))
                if headed:
                    h = next(c for c in headed[0].children if c.controlType == pb.CT_TEXT and c.headingLevel)
                    add("Header holds the author as a button",
                        any(c.controlType == pb.CT_BUTTON for c in h.children),
                        "the author and badges in the heading line come from it", warnOnly=True)
                fields = [len((b.name or "").split(" , ")) for b in bodies]
                add("Body name has at least author and time", min(fields) >= 2,
                    "fewest ' , ' parts: %d" % min(fields))
                replies = [b for b in bodies if " replying to " in (b.name or "").split(" , ")[0]]
                if replies:
                    withJump = [b for b in replies if any(c.controlType == pb.CT_BUTTON
                                and (c.name or "").lower() == "jump to reply" for c in b.children)]
                    add("Replies have a 'Jump To Reply' button", len(withJump) == len(replies),
                        "%d of %d replies" % (len(withJump), len(replies)), warnOnly=True)
                else:
                    skip("Reply structure", "no replies loaded")
            sep = _find(msgs, lambda r: r.controlType == pb.CT_SEPARATOR)
            add("Date dividers are separators", sep is not None, "S moves between them",
                warnOnly=True)
        edit = _find(conv, lambda r: r.controlType == pb.CT_EDIT)
        add("Message box in the conversation", edit is not None, "Ctrl+Shift+Z and focus mode",
            warnOnly=True)

    members = next((c for c in top if c.controlType == pb.CT_GROUP
                    and (c.name or "").lower().startswith("members list for")), None)
    if members is None:
        skip("Member list checks", "member list not shown")
    else:
        entries = _findAll(members, lambda r: r.controlType == pb.CT_LISTITEM and r.hasInvoke)
        add("Member entries are clickable list items", len(entries) > 0, "%d members" % len(entries))

    friends = next((c for c in top if c.controlType == pb.CT_GROUP and c.name == "Friends"), None)
    if friends is None:
        skip("Friends page checks", "not on the Friends page")
    else:
        rows = _findAll(friends, lambda r: r.controlType == pb.CT_LISTITEM and r.children
                        and r.children[0].controlType == pb.CT_BUTTON)
        prefixes = ("open conversation with ", "view pending friend request", "view friend suggestion")
        lead = [r for r in rows if (r.children[0].name or "").lower().startswith(prefixes)]
        if rows:
            add("Friend rows start with a known action ('Open conversation with ...')", len(lead) > 0,
                "%d of %d rows; each row reads as that button plus its details" % (len(lead), len(rows)),
                warnOnly=True)
        else:
            skip("Friend rows", "this tab lists no friends")

    # -- the rendered document --------------------------------------------
    try:
        buf = buf if buf is not None else pb.build(raw)
    except Exception as e:  # noqa: BLE001 - reported, not raised
        add("Browse mode document builds", False, "%s: %s" % (type(e).__name__, e))
        return out
    add("Browse mode document builds", len(buf.lineStarts) > 0,
        "%d lines, %d characters" % (len(buf.lineStarts), len(buf.text)))
    landmarks = [n for n in buf.nodes if n.landmark]
    kinds = set(n.landmark for n in landmarks)
    add("Landmarks: banner, navigation, main",
        set(("banner", "navigation", "main")) <= kinds or (conv is None and set(("banner", "navigation")) <= kinds),
        ", ".join("%s (%s)" % (n.fieldName, n.landmark) for n in landmarks))
    bad = [n.landmark for n in landmarks if n.landmark not in ("banner", "complementary", "contentinfo",
                                                                "main", "navigation", "search", "form", "region")]
    add("Landmark types are ones NVDA knows", not bad, ", ".join(bad) or "all known")
    lines = [buf.text[s:e].strip() for s, e in
             ((s, (buf.lineStarts[i + 1] if i + 1 < len(buf.lineStarts) else len(buf.text)))
              for i, s in enumerate(buf.lineStarts))]
    leaked = [l for l in lines if l in ("Minimize", "Maximize", "Restore", "Close", "Resize Sidebar")]
    add("Window buttons are left out", not leaked, ", ".join(leaked) or "none in the document")
    if conv is not None:
        headings = [n for n in buf.nodes if n.role == "heading" and n.level == 3 and n.parent is not None
                    and pb.isMessageBody(n.parent.raw)]
        bodies = [n for n in buf.nodes if pb.isMessageBody(n.raw)]
        add("Every message starts with an 'author, time' heading",
            bodies and len(headings) == len(bodies) and all(h.start == b.start for h, b in zip(headings, bodies)),
            "%d headings for %d messages" % (len(headings), len(bodies)))
    return out


def summarize(checks):
    counts = dict((s, 0) for s in (PASS, WARN, FAIL, SKIP))
    for c in checks:
        counts[c.status] += 1
    return counts


def report(checks, title="Discord Phoenix self-check"):
    """A plain-text report: one line per check, failures first."""
    counts = summarize(checks)
    lines = [title,
             "%d passed, %d failed, %d warnings, %d skipped" % (counts[PASS], counts[FAIL], counts[WARN], counts[SKIP]),
             ""]
    order = {FAIL: 0, WARN: 1, PASS: 2, SKIP: 3}
    for c in sorted(checks, key=lambda c: order[c.status]):
        lines.append("[%s] %s%s" % (c.status.upper(), c.name, (" - " + c.detail) if c.detail else ""))
    return "\n".join(lines)


def spokenSummary(checks):
    counts = summarize(checks)
    text = "%d passed" % counts[PASS]
    if counts[FAIL]:
        first = next(c for c in checks if c.status == FAIL)
        text += ", %d failed. First: %s" % (counts[FAIL], first.name)
    if counts[WARN]:
        text += ", %d warnings" % counts[WARN]
    return text
