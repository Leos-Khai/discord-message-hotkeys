# -*- coding: utf-8 -*-
# Discord Message Hotkeys - browse mode for Discord's Rust "Phoenix" client.
#
# Phoenix draws its UI with GPUI (window class "Zed::Window") and exposes it
# through AccessKit as plain UI Automation. There is no document in that tree,
# so NVDA never creates a virtual buffer: no browse mode, no quick navigation,
# no Elements List - just object navigation. The Electron client had all of
# that, because Chromium hands NVDA a web document.
#
# This module puts it back. A tree interceptor on the Phoenix window renders
# the whole UIA tree into a flat document (see _phoenixBuffer.py) and gives it
# to NVDA's own BrowseModeDocumentTreeInterceptor, so arrows, quick navigation
# keys, NVDA+F7, find, say all, copy and focus/browse mode switching all behave
# exactly as they do on a web page.
#
# Keeping it current: one UIA cache request with TreeScope_Subtree fetches the
# entire tree in a single cross-process call (~25 ms for 300 elements). The
# document is rebuilt on a background thread while browse mode is in use, and
# the caret is carried across rebuilds by UIA runtime ID, so it stays on the
# same message or control even as new messages arrive.

import ctypes
import threading
import time

import wx
import api
import braille
import browseMode
import config
import controlTypes
import queueHandler
import textInfos
import textInfos.offsets
import ui
import winUser
from logHandler import log
from NVDAObjects import NVDAObject
from scriptHandler import script

try:
    import UIAHandler
    from NVDAObjects.UIA import UIA
except Exception:  # pragma: no cover - UIA support missing entirely
    UIAHandler = None
    UIA = None

try:
    import comtypes
except Exception:  # pragma: no cover
    comtypes = None

from . import _phoenixBuffer as pb

# The window class GPUI gives every top-level window.
PHOENIX_WINDOW_CLASS = "Zed::Window"

# Shared with the settings panel (globalPlugins/discordMessageHotkeys).
CONFIG_SECTION = "discordMessageHotkeys"
CONFIG_KEY_BROWSE_MODE = "phoenixBrowseMode"

# Rebuild cadence while browse mode is in use. Each rebuild is one UIA call plus
# a cheap local walk, done off the main thread.
REFRESH_TICK_MS = 1000
REFRESH_MAX_AGE_SEC = 3.0
# A focus or caret lookup that misses the document rebuilds it on the spot, but
# not more often than this, so a genuinely absent object can't loop.
SYNC_REFRESH_MIN_AGE_SEC = 0.3
# How far up from an object to look for one that is in the document.
OBJECT_LOOKUP_DEPTH = 10
# How far up from the caret to look for something to activate on Enter.
ACTIVATE_LOOKUP_DEPTH = 4
# Pressed on Enter rather than entered in focus mode.
SELECT_ON_ACTIVATE_ROLES = ("treeItem", "tab")

# Loading older history as you read. Phoenix exposes no UIA scroll patterns, but
# GPUI handles WM_MOUSEWHEEL posted to its window, without the pointer moving
# or the window being in front. Tested 2026-11-22 in a group DM: the wheel
# first scrolls through what is loaded (5 notches: nothing new), and Discord
# loads another page only once the view nears the top (10 notches: 20 older
# messages). Newer messages stay loaded while scrolled up, so only this end
# needs it. When the browse mode caret gets within LOAD_MORE_EDGE_ROWS of the
# oldest loaded message, scroll up in steps until something older appears -
# the way moving through the Electron client's list made Chromium load more.
LOAD_MORE_EDGE_ROWS = 2
LOAD_MORE_WHEEL_NOTCHES = 5
LOAD_MORE_STEP_MS = 400
LOAD_MORE_MAX_STEPS = 8
WM_MOUSEWHEEL = 0x020A
WHEEL_DELTA = 120
MESSAGES_LIST_PREFIX = "messages"


def _enum(container, name, fallback):
    try:
        return getattr(container, name)
    except AttributeError:
        return getattr(controlTypes, fallback, None)


def _role(name):
    return _enum(getattr(controlTypes, "Role", None), name, "ROLE_" + name)


def _state(name):
    return _enum(getattr(controlTypes, "State", None), name, "STATE_" + name)


ROLES = {
    "button": _role("BUTTON"), "toggleButton": _role("TOGGLEBUTTON"), "link": _role("LINK"),
    "treeItem": _role("TREEVIEWITEM"), "tab": _role("TAB"), "menuItem": _role("MENUITEM"),
    "checkBox": _role("CHECKBOX"), "radioButton": _role("RADIOBUTTON"), "comboBox": _role("COMBOBOX"),
    "edit": _role("EDITABLETEXT"), "slider": _role("SLIDER"), "spinButton": _role("SPINBUTTON"),
    "progressBar": _role("PROGRESSBAR"), "splitButton": _role("SPLITBUTTON"),
    "headerItem": _role("HEADERITEM"), "dataItem": _role("DATAITEM"), "scrollBar": _role("SCROLLBAR"),
    "thumb": _role("THUMB"), "calendar": _role("CALENDAR"), "text": _role("STATICTEXT"),
    "heading": _role("HEADING"), "graphic": _role("GRAPHIC"), "separator": _role("SEPARATOR"),
    "toolTip": _role("TOOLTIP"), "listItem": _role("LISTITEM"), "list": _role("LIST"),
    "tree": _role("TREEVIEW"), "tabControl": _role("TABCONTROL"), "menu": _role("POPUPMENU"),
    "menuBar": _role("MENUBAR"), "grouping": _role("GROUPING"), "pane": _role("PANE"),
    "window": _role("WINDOW"), "statusBar": _role("STATUSBAR"), "toolBar": _role("TOOLBAR"),
    "header": _role("HEADER"), "table": _role("TABLE"), "dataGrid": _role("DATAGRID"),
    "document": _role("DOCUMENT"), "titleBar": _role("TITLEBAR"), "unknown": _role("UNKNOWN"),
}
ROLE_LANDMARK = _role("LANDMARK")
ROLE_REGION = _role("REGION")
try:
    import aria
    LANDMARK_NAMES = frozenset(aria.landmarkRoles)
except Exception:  # pragma: no cover
    LANDMARK_NAMES = frozenset(("banner", "complementary", "contentinfo", "main", "navigation", "search", "form"))
try:
    _FOCUS_REASON = controlTypes.OutputReason.FOCUS
except AttributeError:  # NVDA before 2021.1
    _FOCUS_REASON = getattr(controlTypes, "REASON_FOCUS", None)
try:
    TREE_ROLE_TEXT = ROLES["tree"].displayString
except Exception:
    TREE_ROLE_TEXT = "tree view"

STATES = {
    "focusable": _state("FOCUSABLE"), "unavailable": _state("UNAVAILABLE"),
    "checked": _state("CHECKED"), "halfChecked": _state("HALFCHECKED"),
    "checkable": _state("CHECKABLE"), "pressed": _state("PRESSED"),
    "selected": _state("SELECTED"), "collapsed": _state("COLLAPSED"),
    "expanded": _state("EXPANDED"), "editable": _state("EDITABLE"),
    "readonly": _state("READONLY"), "linked": _state("LINKED"),
}

# Quick navigation: item type -> test on a rendered node. Types not listed get
# NVDA's "Not supported in this document".
_BUTTON_ROLES = ("button", "toggleButton", "splitButton")
_FORM_FIELD_ROLES = ("edit", "checkBox", "radioButton", "comboBox", "slider", "spinButton") + _BUTTON_ROLES
QUICK_NAV = {
    "heading": lambda n: n.role == "heading",
    "link": lambda n: n.role == "link",
    "button": lambda n: n.role in _BUTTON_ROLES,
    "toggleButton": lambda n: n.role == "toggleButton",
    "formField": lambda n: n.role in _FORM_FIELD_ROLES
    or (n.role in ("list", "tree") and "focusable" in n.states),
    "edit": lambda n: n.role == "edit",
    "checkBox": lambda n: n.role == "checkBox",
    "radioButton": lambda n: n.role == "radioButton",
    "comboBox": lambda n: n.role == "comboBox",
    "list": lambda n: n.role == "list",
    "listItem": lambda n: n.role == "listItem",
    "graphic": lambda n: n.role == "graphic",
    "separator": lambda n: n.role == "separator",
    "landmark": lambda n: bool(n.landmark),
    "tab": lambda n: n.role == "tab",
    "menuItem": lambda n: n.role == "menuItem",
    "slider": lambda n: n.role == "slider",
    "progressBar": lambda n: n.role == "progressBar",
    "grouping": lambda n: n.role == "grouping" and bool(n.fieldName or n.label) and not n.landmark,
    # NVDA's (unbound) article command: one message at a time.
    "article": lambda n: pb.isMessageBody(n.raw),
    "clickable": lambda n: n.isActionable,
    "focusable": lambda n: "focusable" in n.states,
    "container": lambda n: n.role in ("list", "tree", "tabControl", "grouping", "menu", "toolBar")
    or bool(n.landmark),
}
for _level in range(1, 10):
    QUICK_NAV["heading%d" % _level] = (lambda lvl: lambda n: n.role == "heading" and n.level == lvl)(_level)


def _sayAllRunning():
    """Say all walks a range of the document over time; don't rebuild under it."""
    try:
        from speech.sayAll import SayAllHandler  # NVDA 2021.2+
        return bool(SayAllHandler.isRunning())
    except Exception:
        pass
    try:
        import sayAllHandler  # older NVDA
        return bool(sayAllHandler.isRunning())
    except Exception:
        return False


def isBrowseModeEnabled():
    try:
        return bool(config.conf[CONFIG_SECTION][CONFIG_KEY_BROWSE_MODE])
    except Exception:
        return True


def isPhoenixRoot(obj):
    """True for the UIA element of a Phoenix main window (the document root)."""
    if UIA is None or not isinstance(obj, UIA) or not getattr(obj, "UIAIsWindowElement", False):
        return False
    try:
        return obj.windowClassName == PHOENIX_WINDOW_CLASS and (obj.name or "").endswith("Discord")
    except Exception:
        return False


def fetchBuffer(hwnd):
    """Fetch the window's whole UIA tree in one call and flatten it. Any thread."""
    handler = UIAHandler.handler
    request = handler.baseCacheRequest.clone()
    pb.addCacheProperties(request)
    request.TreeScope = pb.TREE_SCOPE_SUBTREE
    # The base request uses the control view; take everything.
    request.TreeFilter = handler.clientObject.RawViewCondition
    element = handler.clientObject.ElementFromHandleBuildCache(hwnd, request)
    return pb.build(pb.rawTreeFromCachedElement(element))


def _runtimeId(obj):
    try:
        return tuple(obj.UIAElement.GetRuntimeId())
    except Exception:
        return None


_EMPTY = pb.Buffer(None)


class PhoenixTextInfo(browseMode.BrowseModeDocumentTextInfo, textInfos.offsets.OffsetsTextInfo):
    """A range of the flattened document. Offsets are plain str indexes."""

    encoding = "utf_32_le"
    detectFormattingAfterCursorMaybeSlow = False
    # There is no insertion point past the end of a browse mode document.
    allowMoveToOffsetPastEnd = False  # NVDA before 2025.1

    def allowMoveToUnitOffsetPastEnd(self, unit):
        return False

    def __init__(self, obj, position):
        # The document this range was made against. Rebuilds swap the
        # interceptor's buffer, never this one, so a range stays self-consistent.
        self._buf = obj._buffer or _EMPTY
        super(PhoenixTextInfo, self).__init__(obj, position)

    # -- text -----------------------------------------------------------------

    def _getStoryLength(self):
        return len(self._buf.text)

    def _getStoryText(self):
        return self._buf.text

    def _getTextRange(self, start, end):
        return self._buf.text[start:end]

    def _getLineOffsets(self, offset):
        return self._buf.lineOffsets(offset)

    def _getParagraphOffsets(self, offset):
        return self._buf.lineOffsets(offset)

    def _getUnitOffsets(self, unit, offset):
        if unit == textInfos.UNIT_CONTROLFIELD:
            chain = self._buf.fieldChain(offset)
            if chain:
                return chain[-1].start, chain[-1].end
            return self._buf.lineOffsets(offset)
        if unit == textInfos.UNIT_FORMATFIELD:
            return self._buf.lineOffsets(offset)
        return super(PhoenixTextInfo, self)._getUnitOffsets(unit, offset)

    # -- caret and selection (virtual, stored on the interceptor) --------------

    def _clamp(self, offset):
        return max(0, min(offset, len(self._buf.text)))

    def _getSelectionOffsets(self):
        doc = self.obj
        start, end = doc._selectionOffsets
        selectionBuffer = doc._selectionBuffer
        if selectionBuffer is not None and selectionBuffer is not self._buf and selectionBuffer.text:
            # The caret was set against another version of the document (a
            # rebuild landed between the two); carry it over by element.
            start, end = doc._remapRange(selectionBuffer, self._buf, start, end)
        return self._clamp(start), self._clamp(end)

    def _setSelectionOffsets(self, start, end):
        self.obj._selectionOffsets = (start, end)
        self.obj._selectionBuffer = self._buf

    def _getCaretOffset(self):
        return self._getSelectionOffsets()[0]

    def _setCaretOffset(self, offset):
        self._setSelectionOffsets(offset, offset)

    # -- objects ---------------------------------------------------------------

    def _getNVDAObjectFromOffset(self, offset):
        node = self._buf.nodeAt(offset)
        obj = self.obj._objectForNode(node) if node is not None else None
        return obj or self.obj.rootNVDAObject

    def _get_focusableNVDAObjectAtStart(self):
        node = self._buf.nodeAt(self._startOffset)
        while node is not None:
            if "focusable" in node.states:
                obj = self.obj._objectForNode(node)
                if obj is not None:
                    return obj
            node = node.parent
        return self.obj.rootNVDAObject

    def _getOffsetsFromNVDAObject(self, obj):
        doc = self.obj
        node = doc._nodeForObject(obj, self._buf)
        if node is None and doc._refreshIfStale():
            # Focus landed on something newer than the document: rebuild once.
            self._buf = doc._buffer or _EMPTY
            node = doc._nodeForObject(obj, self._buf)
        if node is None:
            raise LookupError("object not in the Phoenix document")
        return node.start, node.end

    def _getBoundingRectFromOffset(self, offset):
        obj = self._getNVDAObjectFromOffset(offset)
        location = obj.location if obj is not None else None
        if not location:
            raise LookupError("no location")
        return location

    def _getOffsetFromPoint(self, x, y):
        raise NotImplementedError

    # -- fields ------------------------------------------------------------------

    def getTextWithFields(self, formatConfig=None):
        buf = self._buf
        start, end = self._startOffset, self._endOffset
        if start >= end or not buf.text:
            return []
        commands = []
        openNodes = []
        openFields = []
        offset = start
        line = buf.lineIndex(start)
        lineCount = len(buf.lineStarts)
        while offset < end and line < lineCount:
            lineEnd = buf.lineStarts[line + 1] if line + 1 < lineCount else len(buf.text)
            chain = buf.fieldChain(buf.lineStarts[line])
            common = 0
            while common < len(openNodes) and common < len(chain) and openNodes[common] is chain[common]:
                common += 1
            while len(openNodes) > common:
                openNodes.pop()
                commands.append(textInfos.FieldCommand("controlEnd", openFields.pop()))
            for node in chain[common:]:
                field = self.obj._controlField(node)
                field["_startOfNode"] = node.start >= start
                field["_endOfNode"] = node.end <= end
                commands.append(textInfos.FieldCommand("controlStart", field))
                openNodes.append(node)
                openFields.append(field)
            segmentEnd = min(lineEnd, end)
            commands.append(textInfos.FieldCommand("formatChange", textInfos.FormatField()))
            commands.append(buf.text[offset:segmentEnd])
            offset = segmentEnd
            line += 1
        while openFields:
            commands.append(textInfos.FieldCommand("controlEnd", openFields.pop()))
        return commands

    def _get_clipboardText(self):
        return "\r\n".join(line.rstrip("\n") for line in self.text.split("\n")).strip("\r\n")

    def activate(self):
        self.obj._activatePosition(info=self)


class PhoenixQuickNavItem(browseMode.TextInfoQuickNavItem):

    def __init__(self, itemType, document, node, buf):
        info = document.makeTextInfo(textInfos.offsets.Offsets(node.start, node.end))
        info._buf = buf
        super(PhoenixQuickNavItem, self).__init__(itemType, document, info)
        self.node = node

    @property
    def obj(self):
        return self.document._objectForNode(self.node)

    @property
    def label(self):
        attrs = self.document._controlField(self.node)
        try:
            return self._getLabelForProperties(attrs.get)
        except Exception:
            return self.textInfo.text.strip()

    def isChild(self, parent):
        if self.itemType == "heading":
            return self.node.level > getattr(parent, "node", self.node).level
        return super(PhoenixQuickNavItem, self).isChild(parent)


class PhoenixBrowseDocument(browseMode.BrowseModeDocumentTreeInterceptor):
    """Browse mode over a Phoenix window."""

    TextInfo = PhoenixTextInfo
    # The caret is virtual, so focus events must move it (as for virtual buffers).
    _focusEventMustUpdateCaretPosition = True
    programmaticScrollMayFireEvent = False

    def __init__(self, rootNVDAObject):
        # Set before the base constructor, which may already ask for a TextInfo.
        self._buffer = None
        self._selectionOffsets = (0, 0)
        self._selectionBuffer = None  # the buffer _selectionOffsets refer to
        self._hwnd = rootNVDAObject.windowHandle
        self._loading = False
        self._dirty = False
        self._terminated = False
        self._lastLoadTime = 0.0
        self._generation = 0         # bumped for every load started
        self._appliedGeneration = 0  # the load the current buffer came from
        self._refreshTimer = None
        self._loadMore = None  # state of a running "load older messages"
        super(PhoenixBrowseDocument, self).__init__(rootNVDAObject)

    # -- lifetime ----------------------------------------------------------------

    def terminate(self):
        self._terminated = True
        timer = self._refreshTimer
        self._refreshTimer = None
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass
        super(PhoenixBrowseDocument, self).terminate()

    def _get_isAlive(self):
        return (not self._terminated and isBrowseModeEnabled()
                and bool(winUser.isWindow(self._hwnd)))

    def _get_isReady(self):
        return self._buffer is not None

    def _get_shouldPrepare(self):
        return self._buffer is None and not self._loading and not self._terminated

    def prepare(self):
        self._startLoad()

    def __contains__(self, obj):
        # Everything in a GPUI window is in the one window handle, so this is
        # exact for Phoenix and costs nothing - it runs for every event.
        try:
            return obj.windowHandle == self._hwnd and isinstance(obj, UIA)
        except Exception:
            return False

    # -- loading -------------------------------------------------------------------

    def _startLoad(self):
        if self._loading or self._terminated:
            return
        self._loading = True
        self._dirty = False
        self._generation += 1
        thread = threading.Thread(
            target=self._loadThread, args=(self._generation,),
            name="discordMessageHotkeys.phoenixBrowseLoad")
        thread.daemon = True
        thread.start()

    def _loadThread(self, generation):
        buf = None
        initialized = False
        try:
            if comtypes is not None:
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
                initialized = True
            buf = fetchBuffer(self._hwnd)
        except Exception:
            log.debugWarning("Discord: Phoenix browse mode load failed", exc_info=True)
        finally:
            if initialized:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass
        queueHandler.queueFunction(queueHandler.eventQueue, self._loadDone, buf, generation)

    def _loadDone(self, buf, generation):
        self._loading = False
        if self._terminated:
            return
        self._lastLoadTime = time.time()
        if buf is None or generation < self._appliedGeneration:
            if self._buffer is None:
                # The first load failed: behave like a failed virtual buffer and
                # get out of the way. shouldPrepare retries on the next focus.
                self.passThrough = True
            return
        initial = self._buffer is None
        self._appliedGeneration = generation
        self._swapBuffer(buf)
        if initial:
            self._startRefreshTimer()
            focus = api.getFocusObject()
            if focus is not None and focus.treeInterceptor is self:
                self.event_treeInterceptor_gainFocus()
        elif self._isActive():
            braille.handler.handleUpdate(self)

    def _refreshNow(self):
        """Rebuild synchronously, on the main thread. True if the buffer changed."""
        if self._terminated or UIAHandler is None:
            return False
        self._generation += 1
        generation = self._generation
        try:
            buf = fetchBuffer(self._hwnd)
        except Exception:
            log.debugWarning("Discord: Phoenix browse mode refresh failed", exc_info=True)
            return False
        self._lastLoadTime = time.time()
        self._dirty = False
        self._appliedGeneration = generation
        self._swapBuffer(buf)
        return True

    def _refreshIfStale(self):
        if self._buffer is None or time.time() - self._lastLoadTime < SYNC_REFRESH_MIN_AGE_SEC:
            return False
        return self._refreshNow()

    def _swapBuffer(self, new):
        """Install a rebuilt document, keeping the caret on the same element."""
        old = self._selectionBuffer or self._buffer
        start, end = self._selectionOffsets
        if old is not None and old.text:
            start, end = self._remapRange(old, new, start, end)
        else:
            start = end = 0
        self._buffer = new
        self._selectionOffsets = (start, end)
        self._selectionBuffer = new

    @classmethod
    def _remapRange(cls, old, new, start, end):
        newStart = cls._remap(old, new, start)
        newEnd = newStart if end == start else max(newStart, cls._remap(old, new, end))
        return newStart, newEnd

    @staticmethod
    def _remap(old, new, offset):
        node = old.nodeAt(offset)
        relative = offset - node.start if node is not None else 0
        while node is not None:
            match = new.findNode(node.runtimeId)
            if match is not None:
                last = max(match.start, match.end - 1)
                return min(match.start + relative, last)
            relative = 0  # an ancestor matched: land on its start
            node = node.parent
        return max(0, min(offset, len(new.text) - 1))

    # -- staying current ---------------------------------------------------------

    def _isActive(self):
        if self.passThrough:
            return False
        focus = api.getFocusObject()
        return focus is not None and focus.treeInterceptor is self

    def _startRefreshTimer(self):
        try:
            self._refreshTimer = wx.CallLater(REFRESH_TICK_MS, self._onRefreshTick)
        except Exception:
            self._refreshTimer = None

    def _onRefreshTick(self):
        if self._terminated:
            return
        try:
            if (not self._loading and self._isActive() and not _sayAllRunning()
                    and (self._dirty or time.time() - self._lastLoadTime >= REFRESH_MAX_AGE_SEC)):
                self._startLoad()
        except Exception:
            log.debugWarning("Discord: Phoenix browse mode refresh tick failed", exc_info=True)
        finally:
            if not self._terminated:
                self._startRefreshTimer()

    def _set_passThrough(self, state):
        wasPassThrough = self._passThrough
        super(PhoenixBrowseDocument, self)._set_passThrough(state)
        if wasPassThrough and not state and self._buffer is not None:
            # Back to browse mode after typing or using Discord's own keys:
            # what you read next should be what is on screen now. In the
            # background: this runs inside focus handling, which is still using
            # ranges of the current document.
            self._startLoad()

    # -- loading more messages -------------------------------------------------

    def _set_selection(self, info, *args, **kwargs):
        super(PhoenixBrowseDocument, self)._set_selection(info, *args, **kwargs)
        reason = kwargs.get("reason", args[0] if args else None)
        if reason == _FOCUS_REASON:
            return  # Discord moved focus itself and scrolls on its own
        try:
            self._maybeLoadMore(info)
        except Exception:
            log.debugWarning("Discord: loading more messages failed", exc_info=True)

    def _maybeLoadMore(self, info):
        if info._startOffset != info._endOffset:
            return  # selecting, not moving
        buf = getattr(info, "_buf", None) or self._buffer
        if buf is None:
            return
        row, listNode = self._messageRowAt(buf, info._startOffset)
        if row is None:
            return
        if self._loadMore is not None:
            return  # already loading
        rows = [n for n in buf.nodes if n.parent is listNode]
        if row not in rows[:LOAD_MORE_EDGE_ROWS]:
            return
        self._loadMore = {"list": listNode.runtimeId, "oldest": rows[0].runtimeId, "steps": 0}
        self._loadMoreStep()

    def _loadMoreStep(self):
        state = self._loadMore
        buf = self._buffer
        listNode = buf.findNode(state["list"]) if (state and buf) else None
        if self._terminated or listNode is None or not self._scrollList(listNode, 1):
            self._loadMore = None
            return
        wx.CallLater(LOAD_MORE_STEP_MS, self._loadMoreCheck)

    def _loadMoreCheck(self):
        state = self._loadMore
        if state is None or self._terminated:
            return
        if not self._isActive() or _sayAllRunning() or not self._refreshNow():
            self._loadMore = None
            return
        buf = self._buffer
        listNode = buf.findNode(state["list"])
        rows = [n for n in buf.nodes if n.parent is listNode] if listNode is not None else []
        if rows and rows[0].runtimeId != state["oldest"]:
            # Older messages arrived above; the caret stayed on its message.
            self._loadMore = None
            braille.handler.handleUpdate(self)
            return
        state["steps"] += 1
        if state["steps"] >= LOAD_MORE_MAX_STEPS:
            self._loadMore = None  # the start of the conversation, or Discord is slow
            return
        self._loadMoreStep()

    @staticmethod
    def _messageRowAt(buf, offset):
        """(row, list) for the message row at offset, or (None, None)."""
        node = buf.nodeAt(offset)
        while node is not None:
            parent = node.parent
            if (parent is not None and parent.role == "list"
                    and parent.fieldName.lower().startswith(MESSAGES_LIST_PREFIX)):
                return node, parent
            node = parent
        return None, None

    def _scrollList(self, listNode, direction):
        """Post mouse wheel notches over the message list. True if posted."""
        obj = self._objectForNode(listNode)
        location = obj.location if obj is not None else None
        if not location or not location.width or not location.height:
            return False
        x = location.left + location.width // 2
        y = location.top + location.height // 2
        wParam = ((direction * WHEEL_DELTA) & 0xFFFF) << 16
        lParam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
        for _ in range(LOAD_MORE_WHEEL_NOTCHES):
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_MOUSEWHEEL, wParam, lParam)
        return True

    def _markDirty(self, obj, nextHandler, **kwargs):
        self._dirty = True
        nextHandler()

    event_nameChange = _markDirty
    event_valueChange = _markDirty
    event_stateChange = _markDirty
    event_descriptionChange = _markDirty
    event_liveRegionChange = _markDirty
    event_UIA_elementSelected = _markDirty
    event_UIA_notification = _markDirty
    event_show = _markDirty
    event_hide = _markDirty

    def event_gainFocus(self, obj, nextHandler):
        self._dirty = True
        super(PhoenixBrowseDocument, self).event_gainFocus(obj, nextHandler)

    event_gainFocus.ignoreIsReady = True

    # -- elements ----------------------------------------------------------------

    def _objectForNode(self, node):
        if node is None:
            return None
        if node.obj is None:
            element = node.raw.element
            if element is None or UIA is None:
                return None
            try:
                node.obj = UIA(windowHandle=self._hwnd, UIAElement=element)
            except Exception:
                log.debugWarning("Discord: no NVDAObject for a Phoenix element", exc_info=True)
                return None
        return node.obj

    def _nodeForObject(self, obj, buf):
        root = self.rootNVDAObject
        for _ in range(OBJECT_LOOKUP_DEPTH):
            if obj is None:
                return None
            node = buf.findNode(_runtimeId(obj))
            if node is not None:
                return node
            if obj == root:
                return buf.root
            obj = obj.parent
        return None

    def _controlField(self, node):
        field = textInfos.ControlField()
        role = ROLES.get(node.role) or ROLES["unknown"]
        if node.landmark and node.landmark in LANDMARK_NAMES and ROLE_LANDMARK is not None:
            role = ROLE_LANDMARK
            field["landmark"] = node.landmark
        elif node.landmark:
            # "region" is not an ARIA landmark to NVDA: speech looks the type up
            # in aria.landmarkRoles and raised KeyError: 'region' on every quick
            # navigation key that entered one (NVDA log, 2026-11-22). NVDA has a
            # Region role for it instead: "User status and settings region".
            role = ROLE_REGION or ROLES["grouping"]
        elif node.role == "tree":
            # NVDA presents a tree view as a single-line control, which would
            # say "tree view" again on every server. Present it as the
            # container it is here.
            role = ROLES["grouping"]
            field["roleText"] = TREE_ROLE_TEXT
        field["role"] = role
        field["states"] = set(STATES[s] for s in node.states if STATES.get(s) is not None)
        if node.fieldName:
            field["name"] = node.fieldName
        if node.alwaysReportName:
            field["alwaysReportName"] = True
        if node.level:
            field["level"] = node.level
        if node.description:
            field["description"] = node.description
        if node.childControlCount:
            field["_childcontrolcount"] = node.childControlCount
        field["uniqueID"] = node.runtimeId or ("phoenix", node.index)
        return field

    # -- browse mode hooks ------------------------------------------------------

    def _iterNodesByType(self, itemType, direction="next", pos=None):
        test = QUICK_NAV.get(itemType)
        if test is None:
            raise NotImplementedError
        return self._iterNodes(itemType, test, direction, pos)

    def _iterNodes(self, itemType, test, direction, pos):
        buf = self._buffer or _EMPTY
        offset = pos._startOffset if pos is not None else -1
        if direction == "next":
            for node in buf.nodes:
                if node.start > offset and node.isField and test(node):
                    yield PhoenixQuickNavItem(itemType, self, node, buf)
        elif direction == "previous":
            for node in reversed(buf.nodes):
                if node.start < offset and node.isField and test(node):
                    yield PhoenixQuickNavItem(itemType, self, node, buf)
        elif direction == "up":
            node = buf.nodeAt(max(offset, 0))
            while node is not None:
                if node.isField and test(node):
                    yield PhoenixQuickNavItem(itemType, self, node, buf)
                node = node.parent
        else:
            raise ValueError("unknown direction: %s" % direction)

    def _activatePosition(self, obj=None, info=None):
        if obj is None:
            if info is None:
                info = self.makeTextInfo(textInfos.POSITION_CARET)
            node = info._buf.nodeAt(info._startOffset)
            # Enter on a line inside a control (a DM link's status, say) should
            # press the control, not click the text.
            target = node
            candidate = node
            for _ in range(ACTIVATE_LOOKUP_DEPTH):
                if candidate is None:
                    break
                if candidate.isActionable or candidate.role == "edit":
                    target = candidate
                    break
                candidate = candidate.parent
            obj = self._objectForNode(target)
            while obj is None and target is not None:
                # A line the document made up (a follow-on message's author
                # line) has no element of its own: use the one it belongs to.
                target = target.parent
                obj = self._objectForNode(target)
            if obj is None:
                return
            if target is not None and target.role in SELECT_ON_ACTIVATE_ROLES and target.isActionable:
                # A server, folder or tab: Enter opens it, as clicking would.
                # (Browse mode would otherwise just switch to focus mode on it.)
                self._activateNVDAObject(obj)
                return
        super(PhoenixBrowseDocument, self)._activatePosition(obj=obj)

    def _get_documentConstantIdentifier(self):
        return None

    @script(
        description="Refresh the Discord browse mode document",
        gesture="kb:NVDA+f5",
    )
    def script_refreshBuffer(self, gesture):
        if self._refreshNow():
            ui.message("Refreshed")

    def getCaretNode(self):
        """The rendered node at the browse mode caret, or None."""
        buf = self._buffer
        if buf is None or not buf.text:
            return None
        return buf.nodeAt(self._selectionOffsets[0])

    def getCaretObject(self):
        return self._objectForNode(self.getCaretNode())


class PhoenixWindow(NVDAObject):
    """Overlay on the Phoenix main window: the root of the browse mode document."""

    def _get_treeInterceptorClass(self):
        return PhoenixBrowseDocument

    def _get_shouldCreateTreeInterceptor(self):
        return UIAHandler is not None and getattr(UIAHandler, "handler", None) is not None \
            and isBrowseModeEnabled()
