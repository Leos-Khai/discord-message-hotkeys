# -*- coding: utf-8 -*-
# Discord Message Hotkeys - self-check for the Phoenix client's structure.
#
# Browse mode for Phoenix (_phoenixBuffer.py, _phoenixBrowseMode.py) rests on
# what Discord's accessibility tree looks like: the window class, the names of
# its regions, how a message row is built, and so on. Discord changes its UI
# often, and when it does, browse mode degrades quietly - a region stops being
# a landmark, messages lose their headings - rather than failing loudly.
#
# This module first works out which screen is open (a channel, a DM, Friends,
# Settings, a profile...), then checks every assumption the add-on makes about
# that screen, plus the side panels showing (member list, thread, profile
# panel), and finally the browse mode document built from it. Run it against a
# live tree (NVDA+Ctrl+Shift+F11 in Discord, or tools/phoenix_check.py) or a
# recorded one (tests/). Each check passes, fails, warns, or is skipped. Pure
# Python, no NVDA imports.

try:
    from . import _phoenixBuffer as pb
except ImportError:  # loaded on its own, by tests/ or tools/
    import _phoenixBuffer as pb

PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"

WINDOW_CLASS = "Zed::Window"

# Screen kinds, with how the report names them.
SCREENS = {
    "channel": "text channel",
    "announcement": "announcement channel",
    "forum": "forum channel",
    "voiceChat": "voice channel chat",
    "dm": "direct message",
    "groupDm": "group direct message",
    "friends": "Friends page",
    "discover": "Discover",
    "quests": "Quests",
    "shop": "Shop",
    "nitro": "Nitro",
    "messageRequests": "Message Requests",
    "settings": "Settings",
    "profile": "user profile",
    "inbox": "Inbox",
    "menu": "context menu",
    "modal": "dialog",
    "unknown": "unrecognised screen",
}

# The "Channel header" region's first line names the kind of conversation.
HEADER_KINDS = {
    "text channel": "channel",
    "announcement channel": "announcement",
    "forum channel": "forum",
    "direct message": "dm",
}
# The page title (the first text in the main pane, or the window title).
TITLE_KINDS = {
    "friends": "friends",
    "discover": "discover",
    "servers": "discover",
    "apps": "discover",
    "quests": "quests",
    "shop": "shop",
    "nitro": "nitro",
    "message requests": "messageRequests",
}


class Check(object):
    __slots__ = ("name", "status", "detail")

    def __init__(self, name, status, detail=""):
        self.name = name
        self.status = status
        self.detail = detail

    def __repr__(self):
        return "<Check %s %s: %s>" % (self.status, self.name, self.detail)


class Screen(object):
    """What is on screen: the kind, and the parts the checks look at."""

    def __init__(self, kind):
        self.kind = kind
        self.pane = None
        self.modal = None
        self.top = []          # the main pane's children
        self.conversation = None
        self.header = None
        self.thread = None
        self.members = None
        self.profilePanel = None

    @property
    def label(self):
        return SCREENS.get(self.kind, self.kind)


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


def _lower(r):
    return (r.name or "").strip().lower()


def _isConversation(r):
    lower = _lower(r)
    return r.controlType == pb.CT_GROUP and (
        (lower.endswith("(channel)") and not lower.startswith("members list for"))
        or lower.startswith("text chat for voice channel"))


def _child(raw, controlType=None, name=None, pred=None):
    for c in raw.children:
        if controlType is not None and c.controlType != controlType:
            continue
        if name is not None and c.name != name:
            continue
        if pred is not None and not pred(c):
            continue
        return c
    return None


def detectScreen(raw):
    """Work out which Discord screen a fetched tree shows."""
    modal = _child(raw, pb.CT_WINDOW, pred=lambda c: bool(c.children))
    pane = _child(raw, pb.CT_PANE)
    menu = _child(raw, pb.CT_MENU, pred=lambda c: bool(c.children))
    if menu is not None:
        # A context menu (right-click on a message) opens beside the pane and
        # empties it; NVDA uses focus mode in menus, as on the web.
        screen = Screen("menu")
        screen.modal, screen.pane = menu, pane
        return screen
    if modal is not None:
        screen = Screen("modal")
        if _child(modal, pb.CT_GROUP, "Settings sidebar") is not None:
            screen.kind = "settings"
        elif _lower(modal).endswith("'s profile"):
            screen.kind = "profile"
        elif _lower(modal) == "inbox":
            screen.kind = "inbox"
        screen.modal, screen.pane = modal, pane
        return screen
    screen = Screen("unknown")
    screen.pane = pane
    if pane is None:
        return screen
    top = screen.top = list(pane.children)
    screen.conversation = next((c for c in top if _isConversation(c)), None)
    screen.header = next((c for c in top if c.controlType == pb.CT_GROUP and c.name == "Channel header"), None)
    screen.thread = next((c for c in top if c.controlType == pb.CT_GROUP and _lower(c).endswith("(thread)")), None)
    screen.members = next((c for c in top if c.controlType == pb.CT_GROUP
                           and _lower(c).startswith("members list for")), None)
    screen.profilePanel = next((c for c in top if c.controlType == pb.CT_GROUP
                                and _lower(c).endswith("'s profile")), None)
    if screen.conversation is not None and _lower(screen.conversation).startswith("text chat for voice channel"):
        screen.kind = "voiceChat"
    elif screen.header is not None:
        first = _child(screen.header, pb.CT_TEXT)
        kind = HEADER_KINDS.get(_lower(first) if first is not None else "")
        if kind is None and _find(screen.header, lambda r: r.controlType == pb.CT_BUTTON
                                  and _lower(r).startswith("edit group")):
            kind = "groupDm"
        screen.kind = kind or ("channel" if screen.conversation is not None else "unknown")
    else:
        title = _child(pane, pb.CT_TEXT, pred=lambda c: bool(c.name))
        kinds = [TITLE_KINDS.get(_lower(title)) if title is not None else None,
                 TITLE_KINDS.get((raw.name or "").rsplit(" - Discord", 1)[0].strip().lower())]
        screen.kind = next((k for k in kinds if k), "unknown")
        if screen.kind == "unknown" and next((c for c in top if c.controlType == pb.CT_GROUP
                                              and c.name == "Friends"), None) is not None:
            screen.kind = "friends"
    return screen


class _Checker(object):

    def __init__(self):
        self.out = []

    def add(self, name, ok, detail="", warnOnly=False):
        self.out.append(Check(name, PASS if ok else (WARN if warnOnly else FAIL), detail))
        return ok

    def skip(self, name, why):
        self.out.append(Check(name, SKIP, why))


def runChecks(raw, windowClass=None, buf=None):
    """Check a fetched Phoenix tree. Returns a list of Check, in report order."""
    c = _Checker()
    screen = detectScreen(raw)
    c.add("Screen recognised", screen.kind != "unknown",
          "%s; the checks below are the ones for this screen" % screen.label, warnOnly=True)

    # -- the window -------------------------------------------------------
    if windowClass is not None:
        c.add("Window class is %s" % WINDOW_CLASS, windowClass == WINDOW_CLASS,
              "found %r; browse mode only attaches to this class" % windowClass)
    c.add("Window title ends with 'Discord'", (raw.name or "").endswith("Discord"),
          "title %r; browse mode only attaches to such windows" % raw.name)
    c.add("Main pane under the window", screen.pane is not None,
          "the top-level sections are expected as children of one pane")

    if screen.modal is not None:
        _checkModal(c, screen)
    elif screen.pane is not None:
        _checkSections(c, screen)
        kindCheck = SCREEN_CHECKS.get(screen.kind)
        if kindCheck is not None:
            kindCheck(c, screen)
        if screen.conversation is not None:
            _checkConversation(c, screen.conversation, "Conversation")
        if screen.thread is not None:
            _checkThread(c, screen)
        _checkMembers(c, screen)

    _checkDocument(c, raw, screen, buf)
    return c.out


# -- the window's sections ------------------------------------------------------

def _checkSections(c, screen):
    top = screen.top
    c.add("Top bar: Go back button", any(r.controlType == pb.CT_BUTTON and r.name == "Go back" for r in top),
          "the loose run before the first section is wrapped as the Top bar landmark")
    sidebar = next((r for r in top if r.controlType == pb.CT_GROUP and r.name == "Servers sidebar"), None)
    c.add("Region 'Servers sidebar'", sidebar is not None, "a navigation landmark, and Ctrl+Shift+S")
    if sidebar is not None:
        items = _findAll(sidebar, lambda r: r.controlType == pb.CT_TREEITEM)
        c.add("Server list is a tree of tree items",
              _find(sidebar, lambda r: r.controlType == pb.CT_TREE) is not None and len(items) > 0,
              "%d tree items" % len(items))
        c.add("Server items are selectable", any(i.hasSelectionItem for i in items),
              "Enter opens a server by selecting its item", warnOnly=True)
    if screen.kind == "discover":
        c.skip("Channel or DM list", "Discover shows its own menu there")
    else:
        side = next((r for r in top if r.controlType == pb.CT_GROUP and r.name
                     and (r.name == "Private channels" or _lower(r).endswith("(server)"))), None)
        c.add("Region 'Private channels' or '<server> (server)'", side is not None,
              "the channel or DM list; a navigation landmark, and Ctrl+Shift+C")
        if side is not None:
            lst = _find(side, lambda r: r.controlType == pb.CT_LIST and r.name in ("Direct Messages", "Channels"))
            c.add("Channel/DM list named 'Direct Messages' or 'Channels'", lst is not None,
                  "Ctrl+Shift+C looks for these names")
    user = next((r for r in top if r.controlType == pb.CT_GROUP and r.name == "User status and settings"), None)
    c.add("Region 'User status and settings'", user is not None, "a region, and Ctrl+Shift+X")


# -- conversations ----------------------------------------------------------------

def _checkConversation(c, conv, label):
    c.add("%s named '<name> (channel)'" % label, True, conv.name)
    msgs = _find(conv, lambda r: r.controlType == pb.CT_LIST and _lower(r).startswith("messages"))
    if not c.add("%s: message list named 'Messages in ...'" % label, msgs is not None,
                 "Alt+1..0, Alt+D, auto-read and browse mode all find messages by this name"):
        return
    rows = [r for r in msgs.children if r.controlType == pb.CT_LISTITEM]
    bodies = [b for b in _walk(msgs) if pb.isMessageBody(b)]
    if not bodies:
        # A brand-new channel or DM has only its "This is the start of..." row.
        c.add("%s: message body is a focusable grouping 'author , text , time'" % label,
              len(rows) <= 1, "%d rows, none of them messages" % len(rows))
        return
    c.add("%s: message rows are list items" % label, len(rows) > 0, "%d rows loaded" % len(rows))
    c.add("%s: message body is a focusable grouping 'author , text , time'" % label, True,
          "%d of %d rows" % (len(bodies), len(rows)))
    headed = [b for b in bodies if any(r.controlType == pb.CT_TEXT and r.headingLevel for r in b.children)]
    c.add("%s: message header is a heading inside the body" % label, len(headed) > 0,
          "%d of %d messages start a group with a header" % (len(headed), len(bodies)))
    if headed:
        h = next(r for r in headed[0].children if r.controlType == pb.CT_TEXT and r.headingLevel)
        c.add("%s: header holds the author as a button" % label,
              any(r.controlType == pb.CT_BUTTON for r in h.children),
              "the author and badges in the heading line come from it", warnOnly=True)
    fields = [len((b.name or "").split(" , ")) for b in bodies]
    c.add("%s: body name has at least author and time" % label, min(fields) >= 2,
          "fewest ' , ' parts: %d" % min(fields))
    replies = [b for b in bodies if " replying to " in (b.name or "").split(" , ")[0]]
    if replies:
        withJump = [b for b in replies if any(r.controlType == pb.CT_BUTTON and _lower(r) == "jump to reply"
                                              for r in b.children)]
        c.add("%s: replies have a 'Jump To Reply' button" % label, len(withJump) == len(replies),
              "%d of %d replies" % (len(withJump), len(replies)), warnOnly=True)
    else:
        c.skip("%s: reply structure" % label, "no replies loaded")
    c.add("%s: date dividers are separators" % label,
          _find(msgs, lambda r: r.controlType == pb.CT_SEPARATOR) is not None, "S moves between them",
          warnOnly=True)


def _composer(c, conv, label, required=True):
    edit = _find(conv, lambda r: r.controlType == pb.CT_EDIT)
    c.add("%s: message box" % label, edit is not None, "Ctrl+Shift+Z and focus mode", warnOnly=not required)


def _checkChannel(c, screen):
    if not c.add("Text channel: conversation region", screen.conversation is not None,
                 "the main landmark, and where every message hotkey looks"):
        return
    _composer(c, screen.conversation, "Text channel", required=False)


def _checkAnnouncement(c, screen):
    if not c.add("Announcement channel: conversation region", screen.conversation is not None,
                 "the main landmark"):
        return
    c.add("Announcement channel: Follow button",
          _find(screen.header, lambda r: r.controlType == pb.CT_BUTTON and r.name == "Follow") is not None,
          "in the channel header", warnOnly=True)


def _checkForum(c, screen):
    posts = next((r for r in screen.top if r.controlType == pb.CT_LIST), None)
    if not c.add("Forum: post list beside the header", posts is not None,
                 "becomes the main landmark, named after the channel"):
        return
    items = [r for r in posts.children if r.controlType == pb.CT_LISTITEM]
    cards = [i for i in items if any(r.controlType == pb.CT_BUTTON and _lower(r).startswith("post ")
                                     for r in i.children)]
    c.add("Forum: posts are buttons named 'Post <title>, <n> messages'", len(cards) > 0 or not items,
          "%d of %d posts" % (len(cards), len(items)))
    c.add("Forum: New Post button", _find(posts, lambda r: r.controlType == pb.CT_BUTTON
                                          and r.name == "New Post") is not None, "", warnOnly=True)


def _checkThread(c, screen):
    c.add("Thread panel named '<post> (thread)'", True, screen.thread.name)
    c.add("Thread header region", any(r.controlType == pb.CT_GROUP and r.name == "Thread header"
                                      for r in screen.top), "read as a region before the thread", warnOnly=True)
    _checkConversation(c, screen.thread, "Thread")


def _checkDm(c, screen):
    if not c.add("Direct message: conversation region", screen.conversation is not None, "the main landmark"):
        return
    _composer(c, screen.conversation, "Direct message")
    if screen.profilePanel is None:
        c.skip("Direct message: profile panel", "hidden")
    else:
        c.add("Direct message: profile panel named \"<name>'s profile\"", True, screen.profilePanel.name)


def _checkGroupDm(c, screen):
    if not c.add("Group DM: conversation region", screen.conversation is not None, "the main landmark"):
        return
    _composer(c, screen.conversation, "Group DM")


def _checkVoiceChat(c, screen):
    _composer(c, screen.conversation, "Voice channel chat", required=False)


def _checkFriends(c, screen):
    friends = next((r for r in screen.top if r.controlType == pb.CT_GROUP and r.name == "Friends"), None)
    if not c.add("Friends: page region named 'Friends'", friends is not None, "becomes the main landmark"):
        return
    tabs = [_lower(t) for t in _findAll(friends, lambda r: r.controlType == pb.CT_TABITEM)]
    # Pending and Suggestions only show when there is something in them.
    c.add("Friends: tabs Online, All, Add Friend",
          all(any(t.startswith(want) for t in tabs) for want in ("online", "all", "add friend")),
          ", ".join(tabs) or "no tabs")
    rows = _findAll(friends, lambda r: r.controlType == pb.CT_LISTITEM and r.children
                    and r.children[0].controlType == pb.CT_BUTTON)
    prefixes = ("open conversation with ", "view pending friend request", "view friend suggestion")
    lead = [r for r in rows if _lower(r.children[0]).startswith(prefixes)]
    if rows:
        c.add("Friends: rows start with a known action ('Open conversation with ...')", len(lead) > 0,
              "%d of %d rows; each row reads as that button plus its details" % (len(lead), len(rows)),
              warnOnly=True)
    elif _find(friends, lambda r: r.controlType == pb.CT_BUTTON and r.name == "Send Friend Request"):
        c.add("Friends: Add Friend form", _find(friends, lambda r: r.controlType == pb.CT_EDIT) is not None,
              "an edit box and Send Friend Request")
    else:
        c.skip("Friends: rows", "this tab lists nobody")


def _checkDiscover(c, screen):
    tabs = _findAll(screen.pane, lambda r: r.controlType == pb.CT_TABITEM)
    c.add("Discover: menu tabs (Apps, Servers)", any(_lower(t) == "servers" for t in tabs),
          ", ".join(t.name for t in tabs[:6]))
    cards = _findAll(screen.pane, lambda r: r.controlType == pb.CT_BUTTON and _lower(r) == "view server")
    c.add("Discover: server cards are 'View server' buttons", len(cards) > 0 or len(tabs) > 0,
          "%d cards; read as the server's name and description, then 'View server'" % len(cards),
          warnOnly=True)


def _checkQuests(c, screen):
    tabs = [_lower(t) for t in _findAll(screen.pane, lambda r: r.controlType == pb.CT_TABITEM)]
    c.add("Quests: tabs All Quests and Claimed Quests", "all quests" in tabs, ", ".join(tabs))
    cards = [r for r in screen.top if r.controlType == pb.CT_GROUP and r.focusable and _lower(r).endswith("quest")]
    c.add("Quests: quest cards are focusable groupings named '... QUEST'", len(cards) > 0,
          "%d cards; cards are not landmarks" % len(cards), warnOnly=True)


def _checkShop(c, screen):
    c.add("Shop: 'Discord Shop' menu or 'Search the Shop'",
          _find(screen.pane, lambda r: r.name in ("Discord Shop", "Search the Shop")) is not None, "")


def _checkNitro(c, screen):
    # While loading the page shows a "Nitro" heading; once loaded, a "Nitro" logo.
    c.add("Nitro: 'Gift Nitro' button", _find(screen.pane, lambda r: r.controlType == pb.CT_BUTTON
                                              and r.name == "Gift Nitro") is not None, "")


def _checkMessageRequests(c, screen):
    tabs = [_lower(t) for t in _findAll(screen.pane, lambda r: r.controlType == pb.CT_TABITEM)]
    c.add("Message Requests: tabs Requests and Spam",
          "requests" in tabs and any(t.startswith("spam") for t in tabs), ", ".join(tabs))


SCREEN_CHECKS = {
    "channel": _checkChannel,
    "announcement": _checkAnnouncement,
    "forum": _checkForum,
    "dm": _checkDm,
    "groupDm": _checkGroupDm,
    "voiceChat": _checkVoiceChat,
    "friends": _checkFriends,
    "discover": _checkDiscover,
    "quests": _checkQuests,
    "shop": _checkShop,
    "nitro": _checkNitro,
    "messageRequests": _checkMessageRequests,
}


def _checkMembers(c, screen):
    if screen.members is None:
        c.skip("Member list", "not shown")
        return
    entries = _findAll(screen.members, lambda r: r.controlType == pb.CT_LISTITEM and r.hasInvoke)
    c.add("Member list: entries are clickable list items", len(entries) > 0, "%d members" % len(entries))


# -- modals ------------------------------------------------------------------------

def _checkMenu(c, screen):
    menu = screen.modal
    items = [r for r in menu.children if r.controlType == pb.CT_MENUITEM]
    c.add("Menu: items are menu items", len(items) > 0, "%d items in %r" % (len(items), menu.name))
    c.add("Menu: the main pane is empty behind it", screen.pane is None or not screen.pane.children,
          "", warnOnly=True)


def _checkModal(c, screen):
    if screen.kind == "menu":
        _checkMenu(c, screen)
        return
    modal = screen.modal
    c.add("Modal: the main pane is empty behind it", screen.pane is None or not screen.pane.children,
          "while a modal is open the document is the modal alone", warnOnly=True)
    heading = _child(modal, pb.CT_TEXT, pred=lambda r: r.headingLevel == 1)
    c.add("Modal: named, or headed by a level 1 heading", heading is not None or bool(modal.name),
          "landmark name: %s" % pb.modalName(modal))
    if screen.kind == "inbox":
        tabs = [_lower(t) for t in _findAll(modal, lambda r: r.controlType == pb.CT_TABITEM)]
        c.add("Inbox: tabs Unreads, Mentions", "unreads" in tabs and "mentions" in tabs, ", ".join(tabs))
    if screen.kind == "settings":
        sidebar = _child(modal, pb.CT_GROUP, "Settings sidebar")
        tabs = _findAll(sidebar, lambda r: r.controlType == pb.CT_TABITEM)
        c.add("Settings: sidebar lists pages as tabs", len(tabs) > 5, "%d pages" % len(tabs))
        content = _child(modal, pb.CT_GROUP, pred=lambda r: r.focusable)
        c.add("Settings: page content grouping", content is not None, "")
        rows = _findAll(modal, lambda r: r.controlType == pb.CT_GROUP and len(r.children) >= 2
                        and r.children[0].controlType == pb.CT_TEXT
                        and any(k.controlType in (pb.CT_BUTTON, pb.CT_COMBOBOX, pb.CT_CHECKBOX)
                                and k.name == r.children[0].name for k in r.children[1:]))
        if rows:
            c.add("Settings: options are a label text plus a control of the same name", True,
                  "%d options; each reads as the control, then its description" % len(rows))
        else:
            c.skip("Settings: option rows", "none on this page")
    elif screen.kind == "profile":
        tabs = [_lower(t) for t in _findAll(modal, lambda r: r.controlType == pb.CT_TABITEM)]
        if tabs:
            c.add("Profile: tabs (Activity, Mutual Friends, Mutual Servers)", True, ", ".join(tabs))
        else:
            c.skip("Profile: tabs", "a profile card (from the member list) has none; the full profile does")
        c.add("Profile: 'View Full Profile' or the profile picture",
              _find(modal, lambda r: r.controlType == pb.CT_BUTTON
                    and r.name in ("View Full Profile", "View Profile Picture")) is not None, "", warnOnly=True)
    close = _child(modal, pb.CT_BUTTON, "Close") is not None
    if close or screen.kind == "settings":
        c.add("Modal: Close button", close, "Escape also closes it", warnOnly=True)
    else:
        c.skip("Modal: Close button", "none; Escape closes it")


# -- the rendered document ---------------------------------------------------------

def _lines(buf):
    out = []
    for i, start in enumerate(buf.lineStarts):
        end = buf.lineStarts[i + 1] if i + 1 < len(buf.lineStarts) else len(buf.text)
        out.append((buf.text[start:end].strip(), buf.lineOwners[i]))
    return out


def _checkDocument(c, raw, screen, buf):
    try:
        buf = buf if buf is not None else pb.build(raw)
    except Exception as e:  # noqa: BLE001 - reported, not raised
        c.add("Browse mode document builds", False, "%s: %s" % (type(e).__name__, e))
        return
    c.add("Browse mode document builds", len(buf.lineStarts) > 0,
          "%d lines, %d characters" % (len(buf.lineStarts), len(buf.text)))
    landmarks = [n for n in buf.nodes if n.landmark]
    kinds = set(n.landmark for n in landmarks)
    detail = ", ".join("%s (%s)" % (n.fieldName, n.landmark) for n in landmarks)
    if screen.kind == "menu":
        menuItems = [n for n in buf.nodes if n.role == "menuItem"]
        c.add("Menu items are in the document", len(menuItems) > 0, "%d items" % len(menuItems))
        c.add("Menu: reactions read without their :shortcodes:",
              not any(":" in n.label.split(": ", 1)[-1] for n in menuItems if n.label.startswith("Add Reaction:")),
              "", warnOnly=True)
    elif screen.modal is not None:
        c.add("Landmarks: the modal is the main landmark", "main" in kinds, detail)
        if screen.kind == "settings":
            c.add("Landmarks: Settings sidebar is navigation",
                  any(n.landmark == "navigation" and n.fieldName == "Settings sidebar" for n in landmarks), detail)
    else:
        c.add("Landmarks: banner, navigation and main", set(("banner", "navigation", "main")) <= kinds, detail)
        mains = [n for n in landmarks if n.landmark == "main"]
        c.add("Landmarks: one main", len(mains) == 1, ", ".join(n.fieldName for n in mains))
        if screen.thread is not None:
            c.add("Landmarks: the thread panel is complementary",
                  any(n.landmark == "complementary" and _lower(n.raw).endswith("(thread)") for n in landmarks),
                  detail)
        if screen.kind == "quests":
            c.add("Landmarks: quest cards are not landmarks",
                  not any(n.raw.focusable and n.landmark for n in landmarks), detail)
    known = ("banner", "complementary", "contentinfo", "main", "navigation", "search", "form", "region")
    bad = [n.landmark for n in landmarks if n.landmark not in known]
    c.add("Landmark types are ones NVDA knows", not bad, ", ".join(bad) or "all known")
    windowButtons = set(id(r) for r in raw.children if r.controlType == pb.CT_BUTTON
                        and _lower(r) in ("minimize", "maximize", "restore", "close"))
    leaked = [n.label for n in buf.nodes if id(n.raw) in windowButtons]
    c.add("Window buttons are left out", not leaked, ", ".join(leaked) or "none in the document")
    lines = _lines(buf)
    # The same line twice from siblings is a rendering slip (a label and its
    # control both read); from different containers it is content.
    repeats = [text for (text, owner), (nextText, nextOwner) in zip(lines, lines[1:])
               if text and text == nextText and owner is not nextOwner and owner.parent is nextOwner.parent]
    c.add("No line repeats the one before it", not repeats,
          ", ".join(repeats[:3]) or "each line says something new", warnOnly=True)
    convs = [r for r in (screen.conversation, screen.thread) if r is not None]
    if convs:
        bodies = [n for n in buf.nodes if pb.isMessageBody(n.raw)]
        headings = [n for n in buf.nodes if n.role == "heading" and n.level == 3 and n.parent is not None
                    and pb.isMessageBody(n.parent.raw)]
        c.add("Every message starts with an 'author, time' heading",
              len(headings) == len(bodies) and all(h.start == b.start for h, b in zip(headings, bodies)),
              "%d headings for %d messages" % (len(headings), len(bodies)))
    if screen.kind == "discover":
        c.add("Discover cards read name first, not 'View server'",
              not any(text.startswith("View server") for text, _ in lines), "")
    if screen.kind == "settings":
        doubled = [text for (text, owner), (nextText, nextOwner) in zip(lines, lines[1:])
                   if text and text == nextText]
        c.add("Settings: each option is said once", not doubled, ", ".join(doubled[:3]) or "")


# -- reporting -------------------------------------------------------------------------

def screenOf(checks):
    for c in checks:
        if c.name == "Screen recognised":
            return c.detail.split(";", 1)[0]
    return ""


def summarize(checks):
    counts = dict((s, 0) for s in (PASS, WARN, FAIL, SKIP))
    for c in checks:
        counts[c.status] += 1
    return counts


def report(checks, title="Discord Phoenix self-check"):
    """A plain-text report: one line per check, failures first."""
    counts = summarize(checks)
    lines = [title,
             "Screen: %s" % screenOf(checks),
             "%d passed, %d failed, %d warnings, %d skipped" % (counts[PASS], counts[FAIL], counts[WARN], counts[SKIP]),
             ""]
    order = {FAIL: 0, WARN: 1, PASS: 2, SKIP: 3}
    for c in sorted(checks, key=lambda c: order[c.status]):
        lines.append("[%s] %s%s" % (c.status.upper(), c.name, (" - " + c.detail) if c.detail else ""))
    return "\n".join(lines)


def spokenSummary(checks):
    counts = summarize(checks)
    text = "%s: %d passed" % (screenOf(checks), counts[PASS])
    if counts[FAIL]:
        first = next(c for c in checks if c.status == FAIL)
        text += ", %d failed. First: %s" % (counts[FAIL], first.name)
    if counts[WARN]:
        text += ", %d warnings" % counts[WARN]
    return text
