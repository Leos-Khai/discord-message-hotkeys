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
    # Drop blank lines at the ends; keep at most one blank line inside.
    out = []
    for line in lines:
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def _norm(text):
    return _WS_RE.sub(" ", text.replace("\n", " ")).strip().lower()


class RawNode(object):
    """One UI Automation element, as fetched (or recorded) - the builder's input."""

    __slots__ = (
        "controlType", "name", "value", "focusable", "focused", "enabled",
        "offscreen", "toggleState", "selected", "expandState", "headingLevel",
        "hasInvoke", "hasToggle", "hasSelectionItem", "hasExpandCollapse",
        "hasValue", "valueReadOnly", "runtimeId", "element", "children",
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


class Node(object):
    """A rendered element: its range in the buffer and its control field data."""

    __slots__ = (
        "raw", "role", "parent", "start", "end", "index", "depth", "label",
        "fieldName", "alwaysReportName", "states", "level", "landmark",
        "childControlCount", "isField", "obj",
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


def landmarkFor(name, depth):
    """The ARIA landmark a top-level region maps to, or None.

    Phoenix has no landmarks, but its top-level groupings are exactly the
    regions the Electron client marked as landmarks, so D / Shift+D and the
    Elements List can jump between them again. Depth 2 = window > pane > region.
    """
    lower = name.lower()
    if lower.startswith("members list for"):
        return "complementary"
    if lower.endswith("(channel)") or lower.startswith("text chat for voice channel"):
        return "main"
    if lower.endswith("(server)") or lower in ("servers sidebar", "private channels"):
        return "navigation"
    if depth == 2:
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

        if role in CONTROL_ROLES:
            if role == "edit":
                value = cleanText(raw.value) if isinstance(raw.value, str) else ""
                node.fieldName = name
                node.alwaysReportName = True
                self.emit(node, value or " ")
            elif role in ("slider", "progressBar", "spinButton") and isinstance(raw.value, str) and raw.value:
                self.emit(node, ("%s %s" % (name, cleanText(raw.value))).strip())
            elif raw.children and not self.hasControlDescendant(raw):
                # Only text inside (a DM link's status and server tag, the
                # profile button's user name): fold it into the one line, so
                # moving by line doesn't say "button" once per detail.
                self.emit(node, self.foldedText(raw, name, node) or " ")
                node.end = self.length
                return self._finish(node, parent, role, depth)
            else:
                self.emit(node, name or " ")
            if name:
                childContext = context + [_norm(name)]
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
            if not isTreeRoot and name:
                landmark = landmarkFor(name, depth) if role in ("grouping", "pane") else None
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
                    self.emit(node, name)
                    summary = _norm(name)
                    childContext = context + [summary]
                elif (role in LABELLED_CONTAINER_ROLES or role == "listItem") \
                        and len(name) <= MAX_LABEL_LINE \
                        and not self.covered(name, self.childrenText(raw)) \
                        and not self._isRedundant(_norm(name), context, prevText):
                    self.emit(node, name)
                    childContext = context + [_norm(name)]

        # Children. Text that only repeats a recent sibling ("Blind samurai"
        # beside the server item "2 mentions, Blind samurai", or a friend's
        # user name beside their avatar "sam1234, Idle") is dropped.
        recent = []
        childNodes = 0
        for ch in raw.children:
            if ch.controlType == CT_TITLEBAR:
                continue  # the OS title bar's System / Minimize / Close
            if summary and self.subtreeCovered(ch, summary):
                self.foldSubtree(ch, node)
                continue
            child = self.render(ch, node, depth + 1, childContext, " ".join(recent))
            recent.append(self.rawText(ch))
            del recent[:-SIBLING_DEDUPE_WINDOW]
            if child is not None and child.role == "listItem":
                childNodes += 1
            elif child is not None and role == "tree" and child.role == "treeItem":
                childNodes += 1
        node.childControlCount = childNodes
        node.end = self.length
        return self._finish(node, parent, role, depth)

    def _finish(self, node, parent, role, depth):
        if node.end == node.start:
            return None  # nothing rendered
        if parent is None or role == "window" or (depth == 1 and role == "pane"):
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

    def hasControlDescendant(self, raw):
        for ch in raw.children:
            role = semanticRole(ch)
            if role in CONTROL_ROLES or role in NAME_IN_FIELD_ROLES or self.hasControlDescendant(ch):
                return True
        return False

    def foldedText(self, raw, label, node):
        """label plus the text below raw that label doesn't already say."""
        parts = [label] if label else []
        seen = _norm(label)
        stack = list(reversed(raw.children))
        while stack:
            ch = stack.pop()
            if ch.runtimeId:
                self.folded.append((ch.runtimeId, node))
            text = cleanText(ch.name) or (cleanText(ch.value) if isinstance(ch.value, str) else "")
            normText = _norm(text)
            if normText and _ALNUM_RE.search(normText) and normText not in seen:
                parts.append(text.replace("\n", " "))
                seen += " " + normText
            stack.extend(reversed(ch.children))
        return ", ".join(parts)

    @staticmethod
    def _isRedundant(normText, context, prevText):
        if not _ALNUM_RE.search(normText):
            return True  # "•" and similar decoration
        for ctx in context:
            if normText in ctx:
                return True
        return bool(prevText) and normText in prevText

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
