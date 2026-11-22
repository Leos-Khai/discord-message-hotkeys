# -*- coding: utf-8 -*-
# Discord Message Hotkeys - flattens the Phoenix client's UI Automation tree into
# a browse-mode document: one string of text, split into lines, plus the control
# fields (buttons, links, lists, landmarks...) that enclose each line.
#
# Pure Python with no NVDA imports, so it can be exercised against a live tree
# (or a recorded one) outside NVDA. The NVDA side lives in _phoenixBrowseMode.py.
#
# Why this exists: the Rust "Phoenix" client is a GPUI app (window class
# "Zed::Window") exposed through AccessKit as plain UI Automation. Unlike the
# Electron client it has no document for NVDA to build a virtual buffer from, so
# NVDA never offers browse mode there. We build the document ourselves.

import bisect
import re

# UI Automation control type IDs (UIAutomationClient.h; stable platform values).
CT_BUTTON = 50000
CT_CALENDAR = 50001
CT_CHECKBOX = 50002
CT_COMBOBOX = 50003
CT_EDIT = 50004
CT_HYPERLINK = 50005
CT_IMAGE = 50006
CT_LISTITEM = 50007
CT_LIST = 50008
CT_MENU = 50009
CT_MENUBAR = 50010
CT_MENUITEM = 50011
CT_PROGRESSBAR = 50012
CT_RADIOBUTTON = 50013
CT_SCROLLBAR = 50014
CT_SLIDER = 50015
CT_SPINNER = 50016
CT_STATUSBAR = 50017
CT_TAB = 50018
CT_TABITEM = 50019
CT_TEXT = 50020
CT_TOOLBAR = 50021
CT_TOOLTIP = 50022
CT_TREE = 50023
CT_TREEITEM = 50024
CT_CUSTOM = 50025
CT_GROUP = 50026
CT_THUMB = 50027
CT_DATAGRID = 50028
CT_DATAITEM = 50029
CT_DOCUMENT = 50030
CT_SPLITBUTTON = 50031
CT_WINDOW = 50032
CT_PANE = 50033
CT_HEADER = 50034
CT_HEADERITEM = 50035
CT_TABLE = 50036
CT_TITLEBAR = 50037
CT_SEPARATOR = 50038

# Semantic roles used inside the buffer. The NVDA side maps them to
# controlTypes.Role; keeping strings here keeps this module NVDA-free.
CONTROL_TYPE_ROLES = {
    CT_BUTTON: "button",
    CT_CALENDAR: "calendar",
    CT_CHECKBOX: "checkBox",
    CT_COMBOBOX: "comboBox",
    CT_EDIT: "edit",
    CT_HYPERLINK: "link",
    CT_IMAGE: "graphic",
    CT_LISTITEM: "listItem",
    CT_LIST: "list",
    CT_MENU: "menu",
    CT_MENUBAR: "menuBar",
    CT_MENUITEM: "menuItem",
    CT_PROGRESSBAR: "progressBar",
    CT_RADIOBUTTON: "radioButton",
    CT_SCROLLBAR: "scrollBar",
    CT_SLIDER: "slider",
    CT_SPINNER: "spinButton",
    CT_STATUSBAR: "statusBar",
    CT_TAB: "tabControl",
    CT_TABITEM: "tab",
    CT_TEXT: "text",
    CT_TOOLBAR: "toolBar",
    CT_TOOLTIP: "toolTip",
    CT_TREE: "tree",
    CT_TREEITEM: "treeItem",
    CT_CUSTOM: "unknown",
    CT_GROUP: "grouping",
    CT_THUMB: "thumb",
    CT_DATAGRID: "dataGrid",
    CT_DATAITEM: "dataItem",
    CT_DOCUMENT: "document",
    CT_SPLITBUTTON: "splitButton",
    CT_WINDOW: "window",
    CT_PANE: "pane",
    CT_HEADER: "header",
    CT_HEADERITEM: "headerItem",
    CT_TABLE: "table",
    CT_TITLEBAR: "titleBar",
    CT_SEPARATOR: "separator",
}

# Interactive controls: rendered as one line holding their label, with any
# extra content (children) on the lines after it, inside the control's field.
CONTROL_ROLES = frozenset((
    "button", "toggleButton", "link", "treeItem", "tab", "menuItem", "checkBox",
    "radioButton", "comboBox", "edit", "slider", "spinButton", "progressBar",
    "splitButton", "headerItem", "dataItem", "scrollBar", "thumb", "calendar",
))
# Content: their own text is a line, unless their children already say it.
TEXT_ROLES = frozenset(("text", "heading", "graphic", "separator", "toolTip"))
# Everything else is a container: it encloses its children's lines. A named
# grouping or pane also contributes its name as a line, unless the children
# already say it ("Playing Persona 4 Golden" over "Persona 4 Golden").
LABELLED_CONTAINER_ROLES = frozenset(("grouping", "pane", "statusBar", "toolBar", "header"))
# Containers whose name NVDA announces on entry instead ("Direct Messages list").
NAME_IN_FIELD_ROLES = frozenset(("list", "tree", "tabControl", "menu", "menuBar", "table", "dataGrid"))

# ToggleState / ExpandCollapseState values.
TOGGLE_OFF = 0
TOGGLE_ON = 1
TOGGLE_INDETERMINATE = 2
EXPAND_COLLAPSED = 0
EXPAND_EXPANDED = 1
EXPAND_PARTIAL = 2
EXPAND_LEAF = 3

# Width of the label below which a container's name is worth a line of its own.
# Longer names are summaries of their content (a message row's "author , text ,
# time"), which the children already render in full.
MAX_LABEL_LINE = 120
# How many preceding siblings a text is checked against for repetition.
SIBLING_DEDUPE_WINDOW = 3

_WS_RE = re.compile(r"[ \t ]+")
_ALNUM_RE = re.compile(r"\w", re.UNICODE)
# Chars Chromium/AccessKit use as placeholders, not content.
_PLACEHOLDERS = {ord("￼"): None, ord("﻿"): None, ord("\r"): None}


def cleanText(text):
    """Collapse runs of spaces, drop placeholder chars, keep line breaks."""
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = text.translate(_PLACEHOLDERS)
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    # No blank lines: in browse mode each would just say "blank".
    return "\n".join(line for line in lines if line)


def _norm(text):
    return _WS_RE.sub(" ", text.replace("\n", " ")).strip().lower()


_WORD_RE = re.compile(r"\w+", re.UNICODE)
_LIST_MARKER_RE = re.compile(r"^(\d+[.)]|[a-z][.)]|[•◦▪‣-])$")
# The clan tag Discord appends to names everywhere ("Alex Server Tag: ABCD").
_SERVER_TAG_RE = re.compile(r"\s*Server Tag: [^\s,]+")
_ICON_SUFFIX_RE = re.compile(r", [^,]* icon$", re.IGNORECASE)
_SHORTCODES_RE = re.compile(r"(\s+:[\w+-]+:)+$")
MESSAGE_ACTIONS_NAME = "message actions"
JUMP_TO_REPLY_NAME = "jump to reply"
# Window controls Phoenix draws as children of the window itself (automation
# IDs win-minimize / win-maximize / win-close). Not page content; NVDA's and
# Windows' own commands do the same jobs.
WINDOW_BUTTON_NAMES = frozenset(("minimize", "maximize", "restore", "close"))
RESIZE_HANDLE_NAME = "resize sidebar"
# Names for the sections the builder wraps itself (see _Builder._sections).
TOP_BAR_NAME = "Top bar"
PAGE_CONTENT_NAME = "Page content"
USER_AREA_NAME = "user status and settings"
CHANNEL_HEADER_NAME = "channel header"
THREAD_HEADER_NAME = "thread header"
# Buttons named for what they do, with what they are in their children
# (Discover's "View server" cards, Quests' "View Quest").
ACTION_FIRST_LABELS = frozenset(("view server", "view quest"))
# How far after a label text to look for the control it labels.
LABEL_LOOKAHEAD = 3
SETTINGS_SIDEBAR_NAME = "settings sidebar"


def modalName(raw):
    """A name for a modal window: its own, else "Settings", else its first heading."""
    if raw.name:
        return cleanText(raw.name)
    for ch in raw.children:
        if ch.controlType == CT_GROUP and _norm(ch.name or "") == SETTINGS_SIDEBAR_NAME:
            return "Settings"
    for ch in raw.children:
        if ch.controlType == CT_TEXT and ch.headingLevel and ch.name:
            return cleanText(ch.name)
    return "Dialog"
# Wording that only says what pressing a row does; the row's name follows it.
LEAD_LABEL_PREFIXES = ("open conversation with ",)


def _tokensWithin(text, context):
    """True if every word of text is a word of context ("— 1" in "Admin, 1 member")."""
    words = _WORD_RE.findall(text)
    if not words or not context:
        return False
    contextWords = set(_WORD_RE.findall(context))
    return all(w in contextWords for w in words)


def _stripServerTag(text):
    """Drop the server tag from a name, or from the author part of a message line."""
    if not text or "Server Tag:" not in text:
        return text
    head, sep, rest = text.partition(" , ")
    stripped = _SERVER_TAG_RE.sub("", head).strip()
    return (stripped + sep + rest) if stripped else text


def _isDecoration(raw, normText):
    """Detail that only adds noise inside a line: channel-type icons, server tags."""
    if raw.controlType == CT_IMAGE and normText.endswith(" icon"):
        return True
    return normText.startswith("server tag:")


class RawNode(object):
    """One UI Automation element, as fetched (or recorded) - the builder's input."""

    __slots__ = (
        "controlType", "name", "value", "focusable", "focused", "enabled",
        "offscreen", "toggleState", "selected", "expandState", "headingLevel",
        "hasInvoke", "hasToggle", "hasSelectionItem", "hasExpandCollapse",
        "hasValue", "valueReadOnly", "runtimeId", "element", "children",
        "landmarkHint",
    )

    def __init__(self, controlType=0, name="", value=None, focusable=False, focused=False,
                 enabled=True, offscreen=False, toggleState=None, selected=None,
                 expandState=None, headingLevel=0, hasInvoke=False, hasToggle=False,
                 hasSelectionItem=False, hasExpandCollapse=False, hasValue=False,
                 valueReadOnly=False, runtimeId=None, element=None, children=None):
        self.controlType = controlType
        self.name = name or ""
        self.value = value
        self.focusable = focusable
        self.focused = focused
        self.enabled = enabled
        self.offscreen = offscreen
        self.toggleState = toggleState
        self.selected = selected
        self.expandState = expandState
        self.headingLevel = headingLevel
        self.hasInvoke = hasInvoke
        self.hasToggle = hasToggle
        self.hasSelectionItem = hasSelectionItem
        self.hasExpandCollapse = hasExpandCollapse
        self.hasValue = hasValue
        self.valueReadOnly = valueReadOnly
        self.runtimeId = runtimeId
        self.element = element
        self.children = children if children is not None else []
        # For a grouping the builder made up (a section with no container in
        # the tree): the landmark it should be.
        self.landmarkHint = None


class Node(object):
    """A rendered element: its range in the buffer and its control field data."""

    __slots__ = (
        "raw", "role", "parent", "start", "end", "index", "depth", "label",
        "fieldName", "alwaysReportName", "states", "level", "landmark",
        "childControlCount", "isField", "obj", "description",
    )

    def __init__(self, raw, role, parent, depth):
        self.raw = raw
        self.role = role
        self.parent = parent
        self.depth = depth
        self.start = self.end = 0
        self.index = -1
        self.label = ""
        self.fieldName = ""
        self.alwaysReportName = False
        self.states = set()
        self.level = 0
        self.landmark = None
        self.childControlCount = 0
        self.isField = True
        self.obj = None  # NVDAObject, created on demand by the NVDA side
        self.description = ""  # a tooltip, spoken on focus and quick navigation

    @property
    def runtimeId(self):
        return self.raw.runtimeId

    @property
    def isActionable(self):
        r = self.raw
        return r.hasInvoke or r.hasToggle or r.hasSelectionItem or r.hasExpandCollapse

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def __repr__(self):
        return "<Node %s %r %d-%d>" % (self.role, self.label[:30], self.start, self.end)


def semanticRole(raw):
    role = CONTROL_TYPE_ROLES.get(raw.controlType, "unknown")
    if role == "button" and raw.hasToggle:
        role = "toggleButton"
    elif role == "text" and raw.headingLevel:
        role = "heading"
    return role


def isMessageBody(raw):
    """A Phoenix message: a focusable grouping named "author , text , time".

    Dump of 2026-11-08: LISTITEM > [SEPARATOR date], GROUPING "author , text ,
    time" (focusable) > header, text, embeds, reactions.
    """
    return raw.controlType == CT_GROUP and raw.focusable and " , " in (raw.name or "")


def landmarkFor(name, depth, inMainPane=True):
    """The ARIA landmark a top-level region maps to, or None.

    Phoenix has no landmarks, but its top-level groupings are exactly the
    regions the Electron client marked as landmarks, so D / Shift+D and the
    Elements List can jump between them again. Depth 2 = window > pane >
    region; inside a modal (Settings, a profile) depth 2 is the modal's own
    parts, which are not sections of the window.
    """
    lower = name.lower()
    if lower.startswith("members list for") or lower.endswith("'s profile") \
            or lower.endswith("(thread)"):
        return "complementary"
    if lower.endswith("(channel)") or lower.startswith("text chat for voice channel"):
        return "main"
    if lower.endswith("(server)") or lower == "private channels" or lower.endswith("sidebar") \
            or lower == "breadcrumb":
        return "navigation"
    if depth == 2 and inMainPane:
        return "region"
    return None


class Buffer(object):
    """The flattened document. Immutable once built."""

    def __init__(self, root):
        self.text = ""
        self.nodes = []          # rendered nodes, document (pre-)order
        self.lineStarts = []     # start offset of each line
        self.lineOwners = []     # the node whose text each line is
        self.byRuntimeId = {}
        self.root = root

    # -- queries -------------------------------------------------------------

    def __len__(self):
        return len(self.text)

    def lineIndex(self, offset):
        if not self.lineStarts:
            return -1
        i = bisect.bisect_right(self.lineStarts, offset) - 1
        return max(i, 0)

    def lineOffsets(self, offset):
        i = self.lineIndex(offset)
        if i < 0:
            return 0, 0
        start = self.lineStarts[i]
        end = self.lineStarts[i + 1] if i + 1 < len(self.lineStarts) else len(self.text)
        return start, end

    def nodeAt(self, offset):
        """The node owning the line at offset (innermost content), or None."""
        i = self.lineIndex(min(offset, max(len(self.text) - 1, 0)))
        return self.lineOwners[i] if i >= 0 else None

    def fieldChain(self, offset):
        """Fields enclosing offset, outermost first."""
        node = self.nodeAt(offset)
        chain = []
        while node is not None:
            if node.isField:
                chain.append(node)
            node = node.parent
        chain.reverse()
        return chain

    def findNode(self, runtimeId):
        return self.byRuntimeId.get(runtimeId) if runtimeId else None


class _Builder(object):

    def __init__(self):
        self.parts = []
        self.length = 0
        self.buf = None
        self._rawTextCache = {}
        # (runtimeId, node) for elements merged into an ancestor's line, so
        # focus landing on one still finds its place.
        self.folded = []

    def rawText(self, raw):
        """Every name and value in raw's subtree, normalised - for coverage tests."""
        key = id(raw)
        cached = self._rawTextCache.get(key)
        if cached is not None:
            return cached
        pieces = [_norm(raw.name)]
        if isinstance(raw.value, str) and raw.controlType != CT_HYPERLINK:
            pieces.append(_norm(raw.value))
        for ch in raw.children:
            pieces.append(self.rawText(ch))
        text = " ".join(p for p in pieces if p)
        self._rawTextCache[key] = text
        return text

    def childrenText(self, raw):
        return " ".join(self.rawText(ch) for ch in raw.children)

    @staticmethod
    def covered(label, text):
        """True if every comma-separated part of label appears in text."""
        if not label:
            return True
        if not text:
            return False
        parts = [p for p in (_norm(x) for x in label.replace("\n", " , ").split(" , ")) if p]
        return all(p in text for p in parts) if parts else True

    def emit(self, node, text):
        """Append text as one or more lines owned by node."""
        buf = self.buf
        for line in text.split("\n"):
            buf.lineStarts.append(self.length)
            buf.lineOwners.append(node)
            piece = (line or " ") + "\n"
            self.parts.append(piece)
            self.length += len(piece)

    def render(self, raw, parent, depth, context, prevText):
        role = semanticRole(raw)
        node = Node(raw, role, parent, depth)
        node.start = self.length
        name = cleanText(raw.name)
        node.label = name
        self._setStates(node)
        childContext = context
        summary = None
        isTreeRoot = parent is None or depth <= 1
        skip = set()  # ids of children already said by this node's line
        controlLine = None  # this control's own line, when it has controls inside
        # A clickable list item with only text inside - a member-list entry -
        # is one control, so it gets one line.
        actsAsControl = role == "listItem" and raw.hasInvoke and not self.hasControlDescendant(raw)

        if role in CONTROL_ROLES or actsAsControl:
            if role == "edit":
                value = cleanText(raw.value) if isinstance(raw.value, str) else ""
                node.fieldName = name
                node.alwaysReportName = True
                self.emit(node, value or " ")
            elif role in ("slider", "progressBar", "spinButton") and isinstance(raw.value, str) and raw.value:
                self.emit(node, ("%s %s" % (name, cleanText(raw.value))).strip())
            elif role == "comboBox" and isinstance(raw.value, str) and raw.value:
                # A settings dropdown: "Someone reacts to my messages, All Messages".
                self.emit(node, ", ".join(p for p in (name, cleanText(raw.value)) if p))
                for ch in raw.children:
                    self.foldSubtree(ch, node)
                node.end = self.length
                return self._finish(node, parent, role, depth)
            elif actsAsControl and len(raw.children) > 1:
                self.emit(node, self._memberLine(raw, node) or _stripServerTag(name) or " ")
                node.end = self.length
                return self._finish(node, parent, role, depth)
            elif not self.hasControlDescendant(raw):
                # Only text inside (a DM link's status, the profile button's
                # user name): fold it into the one line, so moving by line
                # doesn't say "button" once per detail.
                label = _stripServerTag(name)
                if role == "link":
                    # "general (text channel), Text icon": the icon is decoration.
                    label = _ICON_SUFFIX_RE.sub("", label)
                elif role == "menuItem":
                    # "Add Reaction: thumbsup :thumbsup: :+1: :thumbup:": the
                    # emoji's shortcodes after its name are for typing, not reading.
                    label = _SHORTCODES_RE.sub("", label)
                node.label = label
                if _norm(label) in ACTION_FIRST_LABELS and raw.children:
                    # "View server" + the server's name and description: say
                    # what it is first, what pressing it does last.
                    details = self.foldedText(raw, "", node)
                    line = ", ".join(p for p in (details, label) if p)
                else:
                    line = self.foldedText(raw, label, node)
                self.emit(node, line or " ")
                node.end = self.length
                return self._finish(node, parent, role, depth)
            else:
                # Controls inside (an activity card's "open profile"): the text
                # parts still make this control's own line - and its label, when
                # it has no name of its own - and the inner controls follow.
                actionFirst = _norm(name) in ACTION_FIRST_LABELS
                parts, seen = ([name], [_norm(name)]) if name and not actionFirst else ([], [])
                for ch in raw.children:
                    if semanticRole(ch) not in CONTROL_ROLES and not self.hasControlDescendant(ch):
                        self._collect(ch, parts, seen, node)
                        skip.add(id(ch))
                if actionFirst:
                    parts.append(name)  # "Avatar Decoration, ..., View Quest"
                controlLine = ", ".join(parts)
                self.emit(node, controlLine or " ")
                controlLine = _norm(controlLine)
            if name or controlLine:
                childContext = context + [controlLine or _norm(name)]
        elif role in TEXT_ROLES:
            text = name
            if not text and isinstance(raw.value, str):
                text = cleanText(raw.value)
            if role == "heading":
                node.level = raw.headingLevel
            if text:
                normText = _norm(text)
                if raw.children and self.covered(text, self.childrenText(raw)):
                    pass  # the children say it
                elif not raw.children and role == "text" and self._isRedundant(normText, context, prevText):
                    pass  # repeats a label just spoken
                else:
                    self.emit(node, text)
                    childContext = context + [normText]
            elif role in ("graphic", "separator") and not raw.children:
                self.emit(node, " ")
        else:
            # Container.
            if depth == 1 and role == "window" and raw.children:
                # A modal (Settings, a full profile) is a window inside the
                # window; while it is open the main pane is empty. The modal is
                # the page: one main landmark.
                node.landmark = "main"
                node.fieldName = modalName(raw)
                node.alwaysReportName = True
            inMainPane = parent is not None and parent.role == "pane" and parent.depth == 1
            if not isTreeRoot and name:
                # Focusable groupings are cards (a quest, a message), not regions;
                # inside a modal only its sidebar and breadcrumb are landmarks.
                landmark = getattr(raw, "landmarkHint", None) or (landmarkFor(name, depth, inMainPane)
                                                if role in ("grouping", "pane") and not raw.focusable else None)
                if landmark == "region" and not inMainPane:
                    landmark = None
                if landmark:
                    node.landmark = landmark
                    node.fieldName = name
                    node.alwaysReportName = True
                elif role in NAME_IN_FIELD_ROLES:
                    node.fieldName = name
                    node.alwaysReportName = True
                elif isMessageBody(raw):
                    # A message: its name is the whole message, "author , text ,
                    # time" (or "author replying to X , ..."). That one line is
                    # what you want on Down arrow; parts of the row that only
                    # repeat it (the author button, date, text) are left out.
                    # A message that starts a group has a header (a level 3
                    # heading: author, server tag, dates); the line takes its
                    # place as the heading, so H moves between authors' posts
                    # as it did in the Electron client.
                    self._renderMessageTop(raw, node, depth, name, skip)
                    summary = _norm(name)
                    childContext = context + [summary]
                elif (role in LABELLED_CONTAINER_ROLES or role == "listItem") \
                        and len(name) <= MAX_LABEL_LINE \
                        and not self.covered(name, self.childrenText(raw)) \
                        and not self._isRedundant(_norm(name), context, prevText):
                    self.emit(node, name)
                    childContext = context + [_norm(name)]

        if role == "listItem" and not actsAsControl:
            self._renderListItemLead(raw, node, depth, skip)
        children = raw.children
        if depth == 1 and role == "pane":
            children = self._sections(raw)
        else:
            children = self._labelledControlsFirst(children, skip)

        # Children. Text that only repeats a recent sibling ("Server Two"
        # beside the server item "2 mentions, Server Two", or a friend's
        # user name beside their avatar "sam1234, Idle") is dropped.
        recent = []
        childNodes = 0
        prevChild = None    # node rendered for the previous child
        recentControls = []  # (line, node) of the last few controls rendered
        afterEdit = False
        # Where Discord puts hover tooltips as plain text after each button:
        # the message toolbar, and the composer's buttons after the message box.
        lowerName = name.lower()
        tooltipZone = lowerName == MESSAGE_ACTIONS_NAME
        isConversation = lowerName.endswith("(channel)") or lowerName.startswith("text chat for voice channel")
        for ch in children:
            if ch.controlType == CT_TITLEBAR:
                continue  # the OS title bar's System / Minimize / Close
            if parent is None and ch.controlType == CT_BUTTON and _norm(ch.name) in WINDOW_BUTTON_NAMES:
                continue  # Discord's own window buttons, beside the pane
            if ch.controlType == CT_SEPARATOR and _norm(ch.name) == RESIZE_HANDLE_NAME:
                continue  # the sidebar's drag handle
            if id(ch) in skip:
                continue
            if summary and self.subtreeCovered(ch, summary):
                self.foldSubtree(ch, node)
                continue
            chRole = semanticRole(ch)
            if chRole in CONTROL_ROLES and chRole != "edit" and not cleanText(ch.name) \
                    and not ch.children and not (isinstance(ch.value, str) and ch.value):
                self.foldSubtree(ch, node)  # an unlabelled, empty button says only "button"
                continue
            if summary and _norm(ch.name).startswith("server tag:"):
                self.foldSubtree(ch, node)  # the clan tag of a replied-to author
                continue
            if summary and _norm(ch.name) == JUMP_TO_REPLY_NAME and chRole == "button":
                prevChild = self._renderReplyContext(raw, ch, node, depth, skip)
                continue
            if prevChild is not None and self._foldTooltip(
                    ch, chRole, prevChild, tooltipZone or (isConversation and afterEdit)):
                continue
            if chRole in ("grouping", "list") and ch.children and recent and not self.hasActionable(ch) \
                    and self.childrenText(ch) and self.childrenText(ch) in " ".join(recent):
                # A group that only repeats what was just said: Settings'
                # breadcrumb, whose one entry is the page heading above it.
                self.foldSubtree(ch, prevChild or node)
                continue
            preview = None
            if chRole in CONTROL_ROLES and not self.hasControlDescendant(ch):
                preview = _norm(self.foldedText(ch, _stripServerTag(cleanText(ch.name)), None))
                chName = _norm(cleanText(ch.name))
                # Inside a control (an Active Now card), same-named buttons are
                # one action shown several ways; elsewhere only exact repeats.
                same = [n for (line, n) in recentControls
                        if line == preview or (controlLine and chName and _norm(n.label) == chName)] \
                    if preview else []
                if same:
                    # The same control again ("View Game Profile" four times
                    # over one game, an embed's image button titled like its
                    # link): one line is enough.
                    self.foldSubtree(ch, same[-1])
                    continue
                if preview and controlLine and preview in controlLine:
                    # Repeats the enclosing control's line (an activity card's
                    # game-name button): say it once.
                    self.foldSubtree(ch, node)
                    continue
            child = self.render(ch, node, depth + 1, childContext, " ".join(recent))
            recent.append(self.rawText(ch))
            del recent[:-SIBLING_DEDUPE_WINDOW]
            prevChild = child
            if child is not None and preview:
                recentControls.append((preview, child))
                del recentControls[:-SIBLING_DEDUPE_WINDOW]
            if chRole == "edit":
                afterEdit = True
            if child is not None and child.role == "listItem":
                childNodes += 1
            elif child is not None and role == "tree" and child.role == "treeItem":
                childNodes += 1
        node.childControlCount = childNodes
        node.end = self.length
        return self._finish(node, parent, role, depth)

    @staticmethod
    def _sections(pane):
        """The main pane's children, with loose runs wrapped as landmarks.

        Discord's F6 moves between the window's sections. Most are named
        groupings ("Servers sidebar", "<name> (channel)") and become landmarks
        as they are, but two have no container in the tree: the top bar (page
        title, Back, Forward, Inbox, Submit a Bug Report) and, on pages like
        Quests, Shop or Message Requests, the page content itself. Each run of
        loose elements becomes a made-up grouping so D reaches it too.
        """
        children = pane.children
        title = ""
        for ch in children:
            if ch.controlType == CT_TEXT and ch.name:
                title = cleanText(ch.name)
                break
        hasMain = any(ch.controlType == CT_GROUP and landmarkFor(ch.name or "", 2) == "main"
                      for ch in children)

        def isNamedGroup(ch):
            return ch.controlType in (CT_GROUP, CT_PANE) and bool(ch.name) and not ch.focusable

        def isSideSection(ch):
            # Sections beside the page content, never part of it.
            if ch.controlType in (CT_SEPARATOR, CT_TITLEBAR):
                return True
            if not isNamedGroup(ch):
                return False
            lower = ch.name.lower()
            return (landmarkFor(ch.name, 2) in ("navigation", "complementary", "main")
                    or lower in (USER_AREA_NAME, CHANNEL_HEADER_NAME, THREAD_HEADER_NAME))

        def runName(run, preferTitle=False):
            # Name a made-up section after what it holds: a named list (a
            # forum's posts), else the page (for page content) or its first
            # heading or text (for a menu).
            for r in run:
                if r.controlType == CT_LIST and r.name:
                    return cleanText(r.name)
            if preferTitle and title:
                return title
            stack = list(reversed(run))
            while stack:
                r = stack.pop()
                if r.controlType == CT_TEXT and r.name:
                    return cleanText(r.name)
                stack.extend(reversed(r.children))
            return title or PAGE_CONTENT_NAME

        out, run = [], []
        state = {"seenSection": False, "mainGiven": hasMain, "seenUserArea": False}

        def flush(content):
            if not run:
                return
            if not state["seenSection"]:
                section = RawNode(CT_GROUP, TOP_BAR_NAME, children=list(run))
                section.landmarkHint = "banner"
            elif not state["seenUserArea"]:
                # Between the server list and the user area is where the
                # channel or DM list goes; a page without one (Discover) puts
                # its own menu there.
                section = RawNode(CT_GROUP, runName(run), children=list(run))
                section.landmarkHint = "navigation"
            elif len(run) == 1 and isNamedGroup(run[0]) and not state["mainGiven"]:
                # A page whose content is already one named grouping
                # ("Friends"): that grouping is the main landmark.
                section = run[0]
                section.landmarkHint = "main"
            else:
                section = RawNode(CT_GROUP, runName(run, preferTitle=True), children=list(run))
                section.landmarkHint = "region" if state["mainGiven"] else "main"
            if section.landmarkHint == "main":
                state["mainGiven"] = True
            out.append(section)
            del run[:]

        for ch in children:
            if isSideSection(ch) or (isNamedGroup(ch) and not state["seenSection"]):
                flush(False)
                if ch.controlType in (CT_GROUP, CT_PANE):
                    state["seenSection"] = True
                if _norm(ch.name or "") == USER_AREA_NAME:
                    state["seenUserArea"] = True
                out.append(ch)
            else:
                # Page content: loose elements and the groupings among them
                # stay together in one section (Shop's menu sits mid-page).
                run.append(ch)
        flush(True)
        return out

    def _renderListItemLead(self, raw, node, depth, skip):
        """A friend row: its first control plus the details after it, as one line.

        Friends list (2026-11-22): LISTITEM > BUTTON "Open conversation with
        Sam", GRAPHIC "sam1234, Idle", TEXT "Sam", TEXT "sam1234",
        TEXT "Idle", BUTTON "Message Sam", BUTTON "More options for Sam".
        Read as is, that is five lines per friend; this makes it "Sam,
        sam1234, Idle" (the button) followed by the two action buttons.
        """
        children = [ch for ch in raw.children if ch.controlType != CT_TITLEBAR]
        if not children:
            return
        lead = children[0]
        leadRole = semanticRole(lead)
        if leadRole not in ("button", "link") or self.hasControlDescendant(lead):
            return
        details = []
        for ch in children[1:]:
            if semanticRole(ch) in CONTROL_ROLES or self.hasControlDescendant(ch):
                break
            details.append(ch)
        if not details:
            return  # nothing to merge; render the row normally
        leadNode = Node(lead, leadRole, node, depth + 1)
        self._setStates(leadNode)
        label = _stripServerTag(cleanText(lead.name))
        for prefix in LEAD_LABEL_PREFIXES:
            if label.lower().startswith(prefix):
                label = label[len(prefix):]
                break
        leadNode.label = label
        parts, seen = ([label], [_norm(label)]) if label else ([], [])
        if lead.runtimeId:
            self.folded.append((lead.runtimeId, leadNode))
        for ch in lead.children:
            self._collect(ch, parts, seen, leadNode)
        for ch in details:
            self._collect(ch, parts, seen, leadNode)
            skip.add(id(ch))
        leadNode.start = self.length
        self.emit(leadNode, ", ".join(parts) or " ")
        leadNode.end = self.length
        skip.add(id(lead))

    def _renderMessageTop(self, raw, node, depth, name, skip):
        """A message as: "author, time" (a heading), what it replies to, the text.

        The body's name is "author , text , time" (or "author replying to X ,
        ..."). The heading says who and when (H moves message by message);
        then the reply's quote, and the text line by line. Links, attachments,
        reactions and "Edited" follow, from the body's children.
        """
        fields = [f.strip() for f in name.split(" , ")]
        if len(fields) >= 3:
            author, text, stamp = fields[0], " , ".join(fields[1:-1]), fields[-1]
        elif len(fields) == 2:
            author, text, stamp = fields[0], fields[1], ""
        else:
            author, text, stamp = "", name, ""
        author = _SERVER_TAG_RE.sub("", author).strip()
        replyTo = ""
        if " replying to " in author:
            author, replyTo = author.split(" replying to ", 1)
            replyTo = _SERVER_TAG_RE.sub("", replyTo).strip()
        header = self._messageHeader(raw)
        if header is not None:
            # The header keeps the author (a button) apart from badges such as
            # "Verified App" (graphics), which the summary runs together.
            names = [cleanText(ch.name) for ch in header.children if ch.controlType == CT_BUTTON
                     and ch.name and not ch.name.startswith("Server Tag:")][:1]
            badges = [cleanText(ch.name) for ch in header.children if ch.controlType == CT_IMAGE and ch.name]
            if names:
                author = ", ".join(names + badges)
        # The heading is who and when: "Alex, 8:49 am"; the message follows
        # on its own lines, so a message of several lines reads in order.
        headingText = ", ".join(p for p in (author, stamp) if p)
        if headingText:
            # A message that starts a group has a header element (a level 3
            # heading: author, server tag, dates); the line stands in for it,
            # and a follow-on message gets the same line, at the same level.
            headingRaw = header if header is not None else RawNode(CT_TEXT, author, headingLevel=3)
            heading = Node(headingRaw, "heading", node, depth + 1)
            heading.level = headingRaw.headingLevel or 3
            heading.label = headingText
            heading.start = self.length
            self.emit(heading, headingText)
            heading.end = self.length
            if header is not None:
                self.foldSubtree(header, heading)
        if header is not None:
            skip.add(id(header))
        jump = next((ch for ch in raw.children if semanticRole(ch) == "button"
                     and _norm(ch.name) == JUMP_TO_REPLY_NAME), None)
        if jump is not None:
            self._renderReplyContext(raw, jump, node, depth, skip)
            skip.add(id(jump))
        elif replyTo:
            self.emit(node, "Replying to %s" % replyTo)
        if text:
            self.emit(node, text)

    def _renderReplyContext(self, body, jump, node, depth, skip):
        """A reply's context as one line: "Replying to @Kim: quoted text".

        Group DM (2026-11-22): the message body starts BUTTON "Jump To Reply",
        BUTTON "@Kim", BUTTON "Server Tag: WXYZ", BUTTON "<quoted text>", then
        the header. The line is the Jump To Reply button, so Enter still jumps.
        """
        children = body.children
        start = children.index(jump)
        mention, quote = "", ""
        for ch in children[start + 1:]:
            if semanticRole(ch) != "button":
                break
            text = cleanText(ch.name)
            if text.lower().startswith("server tag:"):
                pass
            elif text.startswith("@") and not mention:
                mention = text
            elif not quote:
                quote = text.replace("\n", " ")
            else:
                break
            skip.add(id(ch))
        jumpNode = Node(jump, "button", node, depth + 1)
        self._setStates(jumpNode)
        jumpNode.label = cleanText(jump.name)
        # The button is still Jump To Reply, so Enter jumps to the original;
        # the line says what it is: "Replying to @Kim: quoted text".
        line = "Replying to " + ": ".join(p for p in (mention, quote) if p) \
            if (mention or quote) else jumpNode.label
        jumpNode.start = self.length
        self.emit(jumpNode, line)
        jumpNode.end = self.length
        for ch in children[start + 1:]:
            if id(ch) in skip:
                self.foldSubtree(ch, jumpNode)
        return jumpNode

    def _labelledControlsFirst(self, children, skip):
        """Put a control where its separate label was, and drop the label.

        A settings row (2026-11-22): GROUPING > TEXT "Enable Desktop
        Notifications", TEXT "<description>", BUTTON (toggle) "Enable Desktop
        Notifications". Read in order that is the name twice with the
        description between; this gives the toggle and its state, then the
        description.
        """
        out = list(children)
        for i, ch in enumerate(children):
            if ch.children or semanticRole(ch) in CONTROL_ROLES:
                continue
            label = _norm(cleanText(ch.name))
            if not label:
                continue
            for later in children[i + 1:i + 1 + LABEL_LOOKAHEAD]:
                if semanticRole(later) in CONTROL_ROLES and _norm(cleanText(later.name)) == label:
                    j = out.index(later)
                    out.pop(j)
                    out[out.index(ch)] = later
                    break
        return out

    def _foldTooltip(self, raw, role, prevNode, inTooltipZone):
        """Merge a tooltip shown as text after its control. True if merged."""
        if raw.children or role in CONTROL_ROLES or role == "graphic":
            return False
        if prevNode.role not in CONTROL_ROLES:
            return False
        text = cleanText(raw.name) or (cleanText(raw.value) if isinstance(raw.value, str) else "")
        normText = _norm(text)
        if not normText:
            return False
        label = _norm(prevNode.label)
        # "Originally known as Alex#1234. Alex#1234" after the link of that name.
        echoes = (len(label) >= 6 and normText.startswith(label)
                  and (len(normText) == len(label) or not normText[len(label)].isalnum()))
        if not echoes and not (inTooltipZone and prevNode.role in ("button", "toggleButton")):
            return False
        if echoes:
            rest = text.strip()[len(label):].lstrip(" .,:;-")
            if len(_norm(rest)) > 3:
                # "Account Age Sequoia. 7 years, 2 months" after the "Account
                # Age" badge: the label repeats, the rest is the badge's detail.
                raw.name = rest
                return False
        if not echoes and not prevNode.description:
            prevNode.description = text  # NVDA says it on B, Tab and focus
        self.foldSubtree(raw, prevNode)
        return True

    def _memberLine(self, raw, node):
        """A member-list entry from its parts, display name first.

        Member list (2026-11-22): LISTITEM "jo_user, Online Jo Server Tag:
        ABCD Playing ..." > GRAPHIC "jo_user, Online", TEXT "Jo", TEXT
        "Server Tag: ABCD", GROUPING "Playing ...". The item's own name runs
        those together; this gives "Jo, jo_user, Online, Playing ...".
        """
        children = list(raw.children)
        if (len(children) > 1 and children[0].controlType == CT_IMAGE
                and children[1].controlType == CT_TEXT and children[1].name):
            children[0], children[1] = children[1], children[0]
        parts, seen = [], []
        if raw.runtimeId:
            self.folded.append((raw.runtimeId, node))
        for ch in children:
            self._collect(ch, parts, seen, node)
        return ", ".join(parts)

    @staticmethod
    def _messageHeader(raw):
        for ch in raw.children:
            if ch.controlType == CT_TEXT and ch.headingLevel:
                return ch
        return None

    def _finish(self, node, parent, role, depth):
        if node.end == node.start:
            return None  # nothing rendered
        if parent is None or (depth == 1 and role == "pane"):
            node.isField = False
        elif role == "text" and not node.level:
            node.isField = False  # plain text: no field, nothing to announce
        return node

    @staticmethod
    def subtreeCovered(raw, summary):
        """True if raw's subtree says nothing the summary line doesn't.

        Plain buttons whose label is in the summary (the author's name) count
        as covered; any other control - a link, a reaction toggle - keeps the
        subtree, so it stays reachable with K, B and so on.
        """
        stack = [raw]
        while stack:
            r = stack.pop()
            role = semanticRole(r)
            if role in CONTROL_ROLES and role != "button":
                return False
            if role in NAME_IN_FIELD_ROLES:
                return False
            text = _norm(cleanText(r.name) or (r.value if isinstance(r.value, str) else ""))
            if text and _ALNUM_RE.search(text) and text not in summary:
                return False
            stack.extend(r.children)
        return True

    def foldSubtree(self, raw, node):
        stack = [raw]
        while stack:
            r = stack.pop()
            if r.runtimeId:
                self.folded.append((r.runtimeId, node))
            stack.extend(r.children)

    def hasActionable(self, raw):
        """True if anything below raw can be pressed or typed in."""
        return any(semanticRole(r) in CONTROL_ROLES for r in self._descendants(raw))

    @staticmethod
    def _descendants(raw):
        stack = list(raw.children)
        while stack:
            r = stack.pop()
            yield r
            stack.extend(r.children)

    def hasControlDescendant(self, raw):
        for ch in raw.children:
            role = semanticRole(ch)
            if role in CONTROL_ROLES or role in NAME_IN_FIELD_ROLES or self.hasControlDescendant(ch):
                return True
        return False

    def foldedText(self, raw, label, node):
        """label plus the text below raw that label doesn't already say.

        With node None this only previews the line; otherwise the elements
        merged in are mapped to node, so focus on one still finds its place.
        """
        parts, seen = ([label], [_norm(label)]) if label else ([], [])
        for ch in raw.children:
            self._collect(ch, parts, seen, node)
        return ", ".join(parts)

    def _collect(self, raw, parts, seen, node):
        """Append the new text in raw's subtree to parts (see foldedText)."""
        stack = [raw]
        while stack:
            r = stack.pop()
            if node is not None and r.runtimeId:
                self.folded.append((r.runtimeId, node))
            stack.extend(reversed(r.children))
            text = cleanText(r.name) or (cleanText(r.value) if isinstance(r.value, str)
                                         and r.controlType != CT_HYPERLINK else "")
            normText = _norm(text)
            if not normText or not _ALNUM_RE.search(normText) or _isDecoration(r, normText):
                continue
            if any(normText in s for s in seen) or _tokensWithin(normText, " ".join(seen)):
                continue
            # Keep only the comma-separated parts not said yet: "alex_
            # user, Online" after "Alex (direct message), Online" adds
            # just the user name; "Carl-bot, Online" after "Carl-bot", "Online".
            pieces = text.replace("\n", " ").split(", ")
            fresh = [p for p in pieces if _norm(p) and not any(_norm(p) in s for s in seen)]
            if not fresh:
                continue
            text = ", ".join(fresh)
            parts.append(_stripServerTag(text))
            seen.append(_norm(text))

    @staticmethod
    def _isRedundant(normText, context, prevText):
        if not _ALNUM_RE.search(normText) or _LIST_MARKER_RE.match(normText):
            return True  # "•", "1." and similar decoration
        for ctx in context:
            if normText in ctx or _tokensWithin(normText, ctx):
                return True
        return bool(prevText) and (normText in prevText or _tokensWithin(normText, prevText))

    @staticmethod
    def _setStates(node):
        raw = node.raw
        states = node.states
        if raw.focusable:
            states.add("focusable")
        if not raw.enabled:
            states.add("unavailable")
        role = node.role
        if raw.hasToggle and raw.toggleState is not None:
            if role in ("checkBox",):
                if raw.toggleState == TOGGLE_ON:
                    states.add("checked")
                elif raw.toggleState == TOGGLE_INDETERMINATE:
                    states.add("halfChecked")
                states.add("checkable")
            elif raw.toggleState == TOGGLE_ON:
                states.add("pressed")
        if raw.hasSelectionItem and raw.selected:
            states.add("selected")
        if raw.hasSelectionItem and role in ("tab", "treeItem", "listItem", "radioButton"):
            states.add("selectable")
        if raw.hasExpandCollapse and raw.expandState in (EXPAND_COLLAPSED, EXPAND_EXPANDED, EXPAND_PARTIAL):
            if raw.expandState == EXPAND_COLLAPSED:
                states.add("collapsed")
            else:
                states.add("expanded")
        if role == "edit":
            states.add("editable")
            if raw.valueReadOnly:
                states.add("readonly")
        if role in ("list", "listItem"):
            # Read-only lists are announced as containers ("list with 5 items"),
            # the way NVDA presents lists on web pages.
            states.add("readonly")
        if role == "link":
            states.add("linked")


def build(rawRoot):
    """Flatten a RawNode tree into a Buffer."""
    builder = _Builder()
    buf = Buffer(None)
    builder.buf = buf
    root = builder.render(rawRoot, None, 0, [], "")
    buf.text = "".join(builder.parts)
    buf.root = root
    # Document order = order of first line, then depth. Gather every node that
    # owns or encloses a line by walking up from each line owner.
    seen = set()
    order = []
    for owner in buf.lineOwners:
        chain = []
        node = owner
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            chain.append(node)
            node = node.parent
        order.extend(reversed(chain))
    for rid, n in builder.folded:
        buf.byRuntimeId[rid] = n
    for n in order:
        n.index = len(buf.nodes)
        buf.nodes.append(n)
        rid = n.raw.runtimeId
        if rid:
            buf.byRuntimeId[rid] = n
    return buf


# ---------------------------------------------------------------------------
# Reading a UI Automation subtree fetched with one cache request
# ---------------------------------------------------------------------------

# Property IDs (UIAutomationClient.h).
PID_RUNTIME_ID = 30000
PID_CONTROL_TYPE = 30003
PID_NAME = 30005
PID_HAS_KEYBOARD_FOCUS = 30008
PID_IS_KEYBOARD_FOCUSABLE = 30009
PID_IS_ENABLED = 30010
PID_IS_OFFSCREEN = 30022
PID_IS_EXPAND_COLLAPSE_AVAILABLE = 30028
PID_IS_INVOKE_AVAILABLE = 30031
PID_IS_SELECTION_ITEM_AVAILABLE = 30036
PID_IS_TOGGLE_AVAILABLE = 30041
PID_IS_VALUE_AVAILABLE = 30043
PID_VALUE = 30045
PID_VALUE_IS_READ_ONLY = 30046
PID_EXPAND_COLLAPSE_STATE = 30070
PID_SELECTION_ITEM_IS_SELECTED = 30079
PID_TOGGLE_STATE = 30086
PID_HEADING_LEVEL = 30173  # Windows 10 1803+
HEADING_LEVEL_NONE = 80050  # HeadingLevel1 .. HeadingLevel9 are 80051 .. 80059

CACHED_PROPERTY_IDS = (
    PID_RUNTIME_ID, PID_CONTROL_TYPE, PID_NAME, PID_HAS_KEYBOARD_FOCUS,
    PID_IS_KEYBOARD_FOCUSABLE, PID_IS_ENABLED, PID_IS_OFFSCREEN,
    PID_IS_EXPAND_COLLAPSE_AVAILABLE, PID_IS_INVOKE_AVAILABLE,
    PID_IS_SELECTION_ITEM_AVAILABLE, PID_IS_TOGGLE_AVAILABLE,
    PID_IS_VALUE_AVAILABLE, PID_VALUE, PID_VALUE_IS_READ_ONLY,
    PID_EXPAND_COLLAPSE_STATE, PID_SELECTION_ITEM_IS_SELECTED,
    PID_TOGGLE_STATE, PID_HEADING_LEVEL,
)

TREE_SCOPE_SUBTREE = 7  # TreeScope_Element | TreeScope_Children | TreeScope_Descendants

# A hard stop, so a runaway tree can't stall the fetch.
MAX_NODES = 8000


def addCacheProperties(cacheRequest):
    """Add every property the builder reads to a UIA cache request."""
    for pid in CACHED_PROPERTY_IDS:
        try:
            cacheRequest.AddProperty(pid)
        except Exception:
            pass  # e.g. HeadingLevel on a Windows that predates it


def _cached(el, pid, kinds):
    try:
        value = el.GetCachedPropertyValue(pid)
    except Exception:
        return None
    # Unsupported properties come back as UIA's "not supported" sentinel object.
    return value if isinstance(value, kinds) else None


def _rawFromElement(el):
    controlType = _cached(el, PID_CONTROL_TYPE, int) or 0
    runtimeId = _cached(el, PID_RUNTIME_ID, (tuple, list))
    heading = _cached(el, PID_HEADING_LEVEL, int) or 0
    heading = heading - HEADING_LEVEL_NONE if HEADING_LEVEL_NONE < heading <= HEADING_LEVEL_NONE + 9 else 0
    hasValue = bool(_cached(el, PID_IS_VALUE_AVAILABLE, (bool, int)))
    hasToggle = bool(_cached(el, PID_IS_TOGGLE_AVAILABLE, (bool, int)))
    hasSelectionItem = bool(_cached(el, PID_IS_SELECTION_ITEM_AVAILABLE, (bool, int)))
    hasExpandCollapse = bool(_cached(el, PID_IS_EXPAND_COLLAPSE_AVAILABLE, (bool, int)))
    enabled = _cached(el, PID_IS_ENABLED, (bool, int))
    return RawNode(
        controlType=controlType,
        name=_cached(el, PID_NAME, str) or "",
        value=_cached(el, PID_VALUE, str) if hasValue else None,
        focusable=bool(_cached(el, PID_IS_KEYBOARD_FOCUSABLE, (bool, int))),
        focused=bool(_cached(el, PID_HAS_KEYBOARD_FOCUS, (bool, int))),
        enabled=True if enabled is None else bool(enabled),
        offscreen=bool(_cached(el, PID_IS_OFFSCREEN, (bool, int))),
        toggleState=_cached(el, PID_TOGGLE_STATE, int) if hasToggle else None,
        selected=bool(_cached(el, PID_SELECTION_ITEM_IS_SELECTED, (bool, int))) if hasSelectionItem else None,
        expandState=_cached(el, PID_EXPAND_COLLAPSE_STATE, int) if hasExpandCollapse else None,
        headingLevel=heading,
        hasInvoke=bool(_cached(el, PID_IS_INVOKE_AVAILABLE, (bool, int))),
        hasToggle=hasToggle,
        hasSelectionItem=hasSelectionItem,
        hasExpandCollapse=hasExpandCollapse,
        hasValue=hasValue,
        valueReadOnly=bool(_cached(el, PID_VALUE_IS_READ_ONLY, (bool, int))) if hasValue else False,
        runtimeId=tuple(runtimeId) if runtimeId else None,
        element=el,
    )


def _cachedChildren(el):
    try:
        arr = el.GetCachedChildren()
    except Exception:
        return []
    if not arr:
        return []
    try:
        return [arr.GetElement(i) for i in range(arr.Length)]
    except Exception:
        return []


def rawTreeFromCachedElement(rootElement, maxNodes=MAX_NODES):
    """Convert an element fetched with a TreeScope_Subtree cache request to RawNodes.

    Every read is from the client-side cache, so this makes no cross-process
    calls: the one fetch that built the cache did all of that.
    """
    root = _rawFromElement(rootElement)
    stack = [(root, rootElement)]
    count = 1
    while stack:
        raw, el = stack.pop()
        for childEl in _cachedChildren(el):
            if count >= maxNodes:
                return root
            count += 1
            child = _rawFromElement(childEl)
            raw.children.append(child)
            stack.append((child, childEl))
    return root
