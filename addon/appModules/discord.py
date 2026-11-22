# -*- coding: utf-8 -*-
# Discord Message Hotkeys - NVDA app module for the Discord desktop client.
#
#   Alt+1  -> newest message   ...   Alt+9 -> 9th newest   Alt+0 -> 10th newest
#   Alt+1 twice quickly -> reply to that message (same for Alt+2 .. Alt+0)
#   Alt+D  -> move focus to the "New messages" marker (first unread message)
#   Alt+Shift+N -> cycle auto-reading of new messages: off / polite / interrupt
#   Alt+V  -> open the focused message in a read-only window to review it
#   Ctrl+Shift+S -> move focus to the current server in the server list
#   Ctrl+Shift+C -> move focus to the current channel (or first DM) in the channel list
#   Ctrl+Shift+A -> move focus to the first person in Active Now (Friends page)
#   Ctrl+Shift+Z -> move focus to the message box, or the first friend on the Friends page
#   Ctrl+Shift+X -> move focus to the user status and settings area (bottom left)
#   NVDA+Ctrl+Shift+F10 -> write a structure dump to the Downloads folder (debug)
#   NVDA+Ctrl+Shift+F11 -> self-check the new (Phoenix) client; report to Downloads
#
# Named "discord.py" so NVDA auto-loads it for the "Discord.exe" process.
#
# WHY v3 EXISTS (the important fix):
#   Discord's message list is real: NVDA finds a LIST named "Messages in
#   <channel>" with ~50 children. But asking for ALL its children at once
#   (listObj.children) makes Chromium raise "COM call cancelled", because each
#   message row is heavy and the bulk fetch times out. So v3 NEVER bulk-fetches.
#   It walks the rows one at a time from the newest (lastChild) backwards using
#   single navigation calls (lastChild / previous), which are cheap and safe,
#   and only fetches as many as the pressed key needs (Alt+1 = 1 row).

import html
import os
import time
from collections import deque
import wx
import appModuleHandler
import api
import core
import ui
import config
import speech
import braille
import controlTypes
import textInfos
from keyboardHandler import KeyboardInputGesture
from scriptHandler import script
from logHandler import log

# Speech priorities let us distinguish "polite" (queue after current speech)
# from "interrupt" (speak right now). Available on all supported NVDA versions,
# but guard the import so an API change can't stop the module loading.
try:
    from speech.priorities import Spri
except Exception:  # pragma: no cover - very old/very new NVDA
    Spri = None

# Browse mode for the Rust "Phoenix" client. Guarded: if it can't load on some
# NVDA version, the hotkeys must keep working without it.
try:
    from . import _phoenixBrowseMode
except Exception:  # pragma: no cover
    log.error("Discord: Phoenix browse mode unavailable", exc_info=True)
    _phoenixBrowseMode = None
try:
    from . import _phoenixChecks
except Exception:  # pragma: no cover
    log.error("Discord: Phoenix self-check unavailable", exc_info=True)
    _phoenixChecks = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_MESSAGES = 10

# Case-insensitive prefix of the messages-list accessible name.
# Confirmed from a live dump: "Messages in sf6-links".
MESSAGES_LIST_NAME_PREFIX = "messages"

# Caps for the debug dump's whole-tree walk.
SEARCH_NODE_CAP = 15000
SEARCH_MAX_DEPTH = 45

# Locating the list needs no wall-clock budget any more: it is a shallow walk to
# the "(channel)" grouping (window > pane > grouping in Phoenix), never into the
# sidebars' lists and trees. See _searchMessagesList.
CHANNEL_SEARCH_DEPTH = 3    # window > pane > grouping, plus one level of slack
LIST_SEARCH_DEPTH = 4       # from the grouping down to the list (a direct child in Phoenix)
SIBLING_WALK_CAP = 250      # max rows to step through when collecting messages
CHILD_ITER_CAP = 600        # max children to iterate for any one node

# Roles: enum on modern NVDA (2022.1+), constants on older. Support both.
try:
    ROLE_LIST = controlTypes.Role.LIST
    ROLE_LISTITEM = controlTypes.Role.LISTITEM
    ROLE_ARTICLE = controlTypes.Role.ARTICLE
    ROLE_SEPARATOR = controlTypes.Role.SEPARATOR
    ROLE_LANDMARK = controlTypes.Role.LANDMARK
    ROLE_GROUPING = controlTypes.Role.GROUPING
    ROLE_TREEVIEW = controlTypes.Role.TREEVIEW
    ROLE_TREEVIEWITEM = controlTypes.Role.TREEVIEWITEM
    ROLE_PANE = controlTypes.Role.PANE
    ROLE_WINDOW = controlTypes.Role.WINDOW
    ROLE_STATICTEXT = controlTypes.Role.STATICTEXT
    ROLE_LINK = controlTypes.Role.LINK
    ROLE_TOGGLEBUTTON = controlTypes.Role.TOGGLEBUTTON
    ROLE_EDITABLETEXT = controlTypes.Role.EDITABLETEXT
    ROLE_BUTTON = controlTypes.Role.BUTTON
    ROLE_MENUITEM = controlTypes.Role.MENUITEM
    ROLE_POPUPMENU = controlTypes.Role.POPUPMENU
    STATE_FOCUSABLE = controlTypes.State.FOCUSABLE
except AttributeError:
    ROLE_LIST = controlTypes.ROLE_LIST
    ROLE_LISTITEM = controlTypes.ROLE_LISTITEM
    ROLE_ARTICLE = controlTypes.ROLE_ARTICLE
    ROLE_SEPARATOR = controlTypes.ROLE_SEPARATOR
    ROLE_LANDMARK = controlTypes.ROLE_LANDMARK
    ROLE_GROUPING = controlTypes.ROLE_GROUPING
    ROLE_TREEVIEW = controlTypes.ROLE_TREEVIEW
    ROLE_TREEVIEWITEM = controlTypes.ROLE_TREEVIEWITEM
    ROLE_PANE = controlTypes.ROLE_PANE
    ROLE_WINDOW = controlTypes.ROLE_WINDOW
    ROLE_STATICTEXT = controlTypes.ROLE_STATICTEXT
    ROLE_LINK = controlTypes.ROLE_LINK
    ROLE_TOGGLEBUTTON = controlTypes.ROLE_TOGGLEBUTTON
    ROLE_EDITABLETEXT = controlTypes.ROLE_EDITABLETEXT
    ROLE_BUTTON = controlTypes.ROLE_BUTTON
    ROLE_MENUITEM = controlTypes.ROLE_MENUITEM
    ROLE_POPUPMENU = controlTypes.ROLE_POPUPMENU
    STATE_FOCUSABLE = controlTypes.STATE_FOCUSABLE

MESSAGE_ROLES = {ROLE_LISTITEM, ROLE_ARTICLE}
# The child of a row that carries the whole message as its name. The old
# Electron client used an ARTICLE; the Rust "Phoenix" client uses a GROUPING
# (dump of 2026-11-08: LISTITEM > [SEPARATOR date], GROUPING "author , text , time").
MESSAGE_BODY_ROLES = {ROLE_ARTICLE, ROLE_GROUPING}
# The "(channel)" wrapper: a LANDMARK in the old client, a GROUPING in Phoenix.
CHANNEL_ANCHOR_ROLES = {ROLE_LANDMARK, ROLE_GROUPING}
# Roles a "Reply" control could plausibly have. Kept wide: Discord builds its
# menus and toolbars in HTML, so the exact role is Discord's choice, not a
# platform guarantee.
ACTION_ROLES = {ROLE_BUTTON, ROLE_MENUITEM, ROLE_LISTITEM}

# Discord wraps the whole conversation area in a landmark whose accessible name
# ends "(channel)" - confirmed from a live DM dump: "Æthelberht (channel)". It is
# the common ancestor of BOTH the compose box and the messages list, so it is the
# ideal place to start looking: it scopes the search to the conversation and can
# never wander into the servers sidebar or the "Direct Messages" list.
CHANNEL_LANDMARK_SUFFIX = "(channel)"
# Max parent hops from the focused object up to that landmark. Measured at 5 in a
# live DM (compose box depth 23 -> landmark depth 18); 12 leaves generous slack.
ANCHOR_WALK_CAP = 12

# "1".."9" -> 0..8 (count back from newest); "0" -> 9 (10th newest).
KEY_TO_INDEX = {str(n): n - 1 for n in range(1, 10)}
KEY_TO_INDEX["0"] = 9

# ---------------------------------------------------------------------------
# Reply to a message (press the same Alt+number twice, quickly)
# ---------------------------------------------------------------------------

# Discord documents single-key shortcuts on a focused message row (R replies, E
# edits, P pins, + reacts), but they DO NOT work when NVDA moves focus to the row
# programmatically: Discord only arms them in its own "keyboard mode", which it
# enters when you arrow into the list yourself. A synthetic setFocus() leaves that
# state unset, so Discord falls back to its "type anywhere to start composing"
# behaviour and the R is typed into the compose box as a literal letter. Tested on
# device in 0.9.0 - that is exactly what happened. Do not reintroduce the keypress.
#
# So we invoke Discord's own Reply control through the accessibility API instead,
# which needs no keyboard state: find the object named "Reply" and doAction() it.
# Two places to look, in order of preference:
#   1. The message's action toolbar (the buttons revealed alongside a focused or
#      hovered message). Silent and instant when present.
#   2. The message context menu, opened with the Applications key. A non-printable
#      key, so unlike "r" it cannot be swallowed into the compose box.
REPLY_CONTROL_NAME = "reply"
# Bounds for the two searches, in the spirit of every other walk here.
REPLY_SUBTREE_NODE_CAP = 400
REPLY_SUBTREE_MAX_DEPTH = 8
REPLY_MENU_NODE_CAP = 400
REPLY_MENU_MAX_DEPTH = 10
# Time for Discord to build and show the context menu before we search it.
REPLY_MENU_DELAY_MS = 300

# Used only if NVDA's own multi-press timeout can't be read. NVDA's default is
# also 0.5s, so this is the same number from a different source, not a guess.
DOUBLE_PRESS_FALLBACK_SEC = 0.5
# Clamp whatever NVDA reports: too short makes the second press unhittable, too
# long makes two separate reads look like one reply.
DOUBLE_PRESS_MIN_SEC = 0.2
DOUBLE_PRESS_MAX_SEC = 1.5

# setFocus() returns before Chromium has actually moved focus, so the "r" has to
# wait a beat - sent too early it lands on whatever had focus before (usually the
# compose box, where it would be typed as a literal letter). Both steps are
# verified rather than assumed; see _sendReplyKey / _confirmReply.
REPLY_FOCUS_DELAY_MS = 150
# Time for Discord to open the reply composer before we check that it did. Also
# lets NVDA finish announcing the compose box, so our confirmation is not spoken
# into the middle of it (a focus change cancels queued speech).
REPLY_CONFIRM_DELAY_MS = 450

# ---------------------------------------------------------------------------
# Auto-read of incoming messages (opt-in; Alt+Shift+N cycles the mode)
# ---------------------------------------------------------------------------

# Modes, in cycle order: off -> polite -> interrupt -> off.
AUTO_OFF = 0
AUTO_POLITE = 1        # queue behind whatever NVDA is already saying
AUTO_INTERRUPT = 2     # cut in and speak the new message immediately
AUTO_MODE_NAMES = {
    AUTO_OFF: "Auto-read off",
    AUTO_POLITE: "Auto-read new messages: polite",
    AUTO_INTERRUPT: "Auto-read new messages: interrupt",
}

# Config section + key that persist the mode across NVDA restarts. The settings
# panel (globalPlugins/discordMessageHotkeys) and the hotkey share this key.
CONFIG_SECTION = "discordMessageHotkeys"
CONFIG_KEY_MODE = "autoReadMode"
# Browse mode in the Phoenix client (see _phoenixBrowseMode.py).
CONFIG_KEY_BROWSE_MODE = "phoenixBrowseMode"
config.conf.spec[CONFIG_SECTION] = {
    CONFIG_KEY_MODE: "integer(default=0, min=0, max=2)",
    CONFIG_KEY_BROWSE_MODE: "boolean(default=True)",
}

# How many recently-announced messages to remember, to avoid re-reading a
# message when Chromium recycles/re-shows its row (e.g. while scrolling).
RECENT_ANNOUNCED_CAP = 30
# When auto-read is on, how far back from the newest row to look for the newest
# real message (skipping date/"new" separators). Small: the newest is at/near
# the bottom. Also the max number of new messages announced per poll (bursts).
NEWEST_ROW_SCAN = 6
# Auto-read polling: Discord does not reliably fire object events for new
# message rows, so a light timer is the workhorse. Every tick (while auto-read
# is on and Discord is focused) it cheaply re-reads the newest row and speaks
# anything new. When off it is a single config read - effectively free.
AUTO_POLL_INTERVAL_MS = 1500
# When auto-read is OFF the tick still runs, but only to keep the list cache warm
# so Alt+1 never pays for a cold search. Cache warmth has no deadline the way an
# incoming message does, so poll far less often - same benefit, a third of the
# wakeups. (Warming at the auto-read cadence would be pure waste.)
IDLE_POLL_INTERVAL_MS = 5000
# Don't re-run the (potentially costly) full list search from the poller more
# often than this when there is no valid cached list, e.g. on a non-channel
# screen. On an open channel the cached list stays valid, so no search happens.
SEARCH_THROTTLE_SEC = 3.0


try:
    from exceptions import CallCancelled  # NVDA's watchdog cancelling a stuck COM call
except Exception:  # pragma: no cover
    CallCancelled = None
try:
    from comtypes import COMError
except Exception:  # pragma: no cover
    COMError = None
# RPC_E_CALL_CANCELED (0x8001011F) and RPC_E_SERVERCALL_RETRYLATER (0x8001010A).
TRANSIENT_HRESULTS = {-2147417825, -2147417846}


def _isTransient(e):
    if CallCancelled is not None and isinstance(e, CallCancelled):
        return True
    return COMError is not None and isinstance(e, COMError) and e.hresult in TRANSIENT_HRESULTS


def getAutoReadMode():
    try:
        return int(config.conf[CONFIG_SECTION][CONFIG_KEY_MODE])
    except Exception:
        return AUTO_OFF


def setAutoReadMode(mode):
    config.conf[CONFIG_SECTION][CONFIG_KEY_MODE] = int(mode)


class AppModule(appModuleHandler.AppModule):

    scriptCategory = "Discord Message Hotkeys"

    def __init__(self, *args, **kwargs):
        super(AppModule, self).__init__(*args, **kwargs)
        self._cachedList = None  # cached messages LIST, revalidated each use
        # Full text of recently auto-announced messages, for de-duplication.
        self._recentAnnounced = deque(maxlen=RECENT_ANNOUNCED_CAP)
        # Have we seeded the "already seen" set for the current channel yet?
        self._autoReadPrimed = False
        # Name of the list we primed against, to notice channel switches.
        self._autoReadChannel = None
        # Throttle for full list searches driven by the poller.
        self._lastSearchTime = 0.0
        # Last read hotkey and when it was pressed, for double-press-to-reply.
        self._lastReadKey = None
        self._lastReadTime = 0.0
        # Repeating timer that drives auto-read (created on the main thread).
        self._pollTimer = None
        self._scheduleAutoPoll()

    def terminate(self, *args, **kwargs):
        try:
            if self._pollTimer is not None:
                self._pollTimer.Stop()
        except Exception:
            pass
        self._pollTimer = None
        super(AppModule, self).terminate(*args, **kwargs)

    def chooseNVDAObjectOverlayClasses(self, obj, clsList):
        # The Phoenix main window becomes the root of a browse mode document.
        # Runs for every object Discord creates, so the test is a few cheap
        # attribute reads; the Electron client never matches it.
        if _phoenixBrowseMode is not None and _phoenixBrowseMode.isPhoenixRoot(obj):
            clsList.insert(0, _phoenixBrowseMode.PhoenixWindow)

    # -----------------------------------------------------------------------
    # Small safe helpers (single COM calls, with a light retry)
    # -----------------------------------------------------------------------

    @staticmethod
    def _safe(func, retries=2):
        """Call func(), retrying only transient errors (a cancelled or busy COM call).

        Anything else - a dead object, an unsupported property - fails the same
        way every time, so it returns None at once instead of sleeping 40ms.
        """
        for attempt in range(retries + 1):
            try:
                return func()
            except Exception as e:
                if attempt < retries and _isTransient(e):
                    time.sleep(0.02)
                else:
                    return None
        return None

    def _role(self, obj):
        return self._safe(lambda: obj.role)

    def _name(self, obj):
        return self._safe(lambda: obj.name)

    def _iterChildren(self, obj):
        """Yield an object's children one at a time via firstChild/next.

        This avoids the bulk `obj.children` fetch, which Chromium cancels on
        Discord's heavy message list.
        """
        child = self._safe(lambda: obj.firstChild)
        count = 0
        while child is not None and count < CHILD_ITER_CAP:
            count += 1
            yield child
            child = self._safe(lambda c=child: c.next)

    # -----------------------------------------------------------------------
    # Locate the messages list (cached + bounded)
    # -----------------------------------------------------------------------

    def _listStillValid(self, obj, role=None):
        if obj is None:
            return False
        if role is None:
            role = self._role(obj)
        if role != ROLE_LIST:  # role first: most callers reject on it alone
            return False
        name = self._name(obj)
        return bool(name) and name.lower().startswith(MESSAGES_LIST_NAME_PREFIX)

    def _isChannelAnchor(self, obj, role):
        if role not in CHANNEL_ANCHOR_ROLES:
            return False
        name = (self._name(obj) or "").strip().lower()
        # "Members list for spam (channel)" sits beside the conversation and also ends
        # in "(channel)"; a voice channel's chat is "Text chat for voice channel X".
        # A forum post opens beside the post list as "<post> (thread)", with its
        # own message list.
        return ((name.endswith(CHANNEL_LANDMARK_SUFFIX) and not name.startswith("members list for"))
                or name.startswith("text chat for voice channel") or name.endswith("(thread)"))

    def _findMessagesList(self):
        if self._listStillValid(self._cachedList):
            return self._cachedList
        self._cachedList = self._searchMessagesList()
        return self._cachedList

    def _channelAnchor(self):
        """Return the "<name> (channel)" landmark around the focus, or None.

        Walking UP from the focused object is enormously cheaper than sweeping
        down from the foreground window: measured on a live DM, anchoring here
        costs ~119 COM calls against ~490 for the full-tree search, because the
        landmark is only ~5 parent hops from the compose box and its subtree is
        just the conversation.

        It also self-corrects on a channel switch - focus moves, so the anchor
        moves - and it is the cheap bail-out on non-channel screens (Friends,
        Home, Settings), where no such landmark exists in the focus ancestry.
        """
        node = self._safe(lambda: api.getFocusObject())
        steps = 0
        while node is not None and steps < ANCHOR_WALK_CAP:
            steps += 1
            if self._isChannelAnchor(node, self._role(node)):
                return node
            node = self._safe(lambda n=node: n.parent)
        return None

    def _searchMessagesList(self):
        """Find the messages LIST under the "<name> (channel)" grouping.

        The grouping comes from the focus ancestry when focus is in the
        conversation (cheapest), else from a shallow window search - the case
        after Ctrl+Shift+S / Ctrl+Shift+C, when focus is in a sidebar. Neither
        walk descends into lists or trees, so the sidebars' hundreds of rows are
        never visited: a few dozen COM calls, no wall-clock budget needed. On a
        screen with no channel (Friends, Settings) it returns None just as fast.
        """
        anchor = self._channelAnchor() or self._findInWindow(
            self._isChannelAnchor, maxDepth=CHANNEL_SEARCH_DEPTH)
        if anchor is None:
            return None
        return self._findInWindow(
            lambda o, r: self._listStillValid(o, r), root=anchor, maxDepth=LIST_SEARCH_DEPTH)

    # -----------------------------------------------------------------------
    # Collect recent messages WITHOUT a bulk children fetch
    # -----------------------------------------------------------------------

    def _iterMessageRows(self, listObj, limit):
        """Yield up to `limit` message rows, newest first, one COM step at a time.

        The lazy twin of _collectRecentMessages. It exists for the auto-read
        poller, whose overwhelmingly common outcome is "nothing new": that only
        needs the newest row, but _collectRecentMessages eagerly walked all
        NEWEST_ROW_SCAN (6) of them before the caller could look at the first and
        stop. Yielding lets the poller pay for one row (~2 COM calls) in the
        steady state instead of six (~13), every 1.5s, forever.

        No text fallback here - that only matters to the read hotkeys, which keep
        using _collectRecentMessages.
        """
        node = self._safe(lambda: listObj.lastChild)
        steps = 0
        found = 0
        while node is not None and steps < SIBLING_WALK_CAP and found < limit:
            steps += 1
            if self._role(node) in MESSAGE_ROLES:
                found += 1
                yield node
            node = self._safe(lambda n=node: n.previous)

    def _collectRecentMessages(self, listObj, limit):
        """Return up to `limit` message rows, newest first.

        Walks from listObj.lastChild backwards via `previous`. Each step is a
        single, cheap navigation call - the opposite of the bulk fetch that
        Chromium was cancelling.
        """
        walked = []  # list of (obj, role) in newest-first order
        node = self._safe(lambda: listObj.lastChild)
        steps = 0
        while node is not None and steps < SIBLING_WALK_CAP:
            steps += 1
            role = self._role(node)
            walked.append((node, role))
            # Stop early once we have enough proper message rows.
            if sum(1 for (_, r) in walked if r in MESSAGE_ROLES) >= limit:
                break
            node = self._safe(lambda n=node: n.previous)

        matches = [o for (o, r) in walked if r in MESSAGE_ROLES]
        if matches:
            return matches[:limit]
        # Fallback: if Discord ever changes the row role, use any walked node
        # that actually contains text.
        withText = [o for (o, _) in walked if self._objectText(o)]
        return withText[:limit]

    # Chars that Chromium/IA2 uses as placeholders, not real content:
    #   U+FFFC OBJECT REPLACEMENT CHARACTER - stands in for an embedded object
    #           (a child accessible), e.g. the ARTICLE inside each message row.
    #   U+FEFF ZERO WIDTH NO-BREAK SPACE - Discord's empty compose-box filler.
    _PLACEHOLDER_CHARS = "￼﻿"

    def _findChildArticle(self, obj):
        """Return obj's message-body child (ARTICLE or GROUPING), if any.

        A Discord message row is a LISTITEM whose body child's accessible NAME
        is the whole message ("author , text , time"). In Phoenix a date divider
        may come first, so skip non-body children. One cheap firstChild/next
        walk - no bulk fetch.
        """
        for ch in self._iterChildren(obj):
            if self._role(ch) in MESSAGE_BODY_ROLES:
                return ch
        return None

    def _objectText(self, obj):
        # The row itself (a LISTITEM) has no useful text: makeTextInfo returns
        # only U+FFFC placeholders standing in for its child ARTICLE. Read the
        # ARTICLE, whose accessible name carries the full message.
        if self._role(obj) not in MESSAGE_BODY_ROLES:
            article = self._findChildArticle(obj)
            if article is not None:
                obj = article
        name = self._name(obj)
        if name:
            name = name.strip()
            if name:
                return name
        # Fallback: flatten the text, but drop the placeholder chars so an
        # all-placeholder result (e.g. '￼') is treated as empty, not spoken.
        info = self._safe(lambda: obj.makeTextInfo(textInfos.POSITION_ALL))
        if info is not None:
            try:
                text = info.text
                if text:
                    for ch in self._PLACEHOLDER_CHARS:
                        text = text.replace(ch, "")
                    text = text.strip()
                    if text:
                        return text
            except Exception:
                pass
        return ""

    def _readMessage(self, indexFromNewest):
        listObj = self._findMessagesList()
        if listObj is None:
            self._noMessagesHere("No messages here. Open a text channel or DM to read messages.")
            return
        needed = indexFromNewest + 1
        messages = self._collectRecentMessages(listObj, needed)
        if len(messages) < needed:
            if not messages:
                # List was found but rows couldn't be read - drop the cache so
                # the next press re-locates a fresh list object.
                self._cachedList = None
                ui.message("Couldn't read the messages. Try again, or run the debug dump command.")
            else:
                ui.message("Only %d messages are loaded." % len(messages))
            return
        text = self._objectText(messages[indexFromNewest])  # newest-first
        ui.message(text if text else "Message %d could not be read." % needed)

    # -----------------------------------------------------------------------
    # Read commands
    # -----------------------------------------------------------------------

    @staticmethod
    def _doublePressTimeout():
        """How long after a read press a second press counts as "reply to that".

        Deliberately NVDA's own multi-press timeout, so this matches every other
        double-press command the user already knows (and follows it if they
        change it in Keyboard settings).
        """
        try:
            # NVDA stores this in milliseconds (configSpec: default=500).
            timeout = float(config.conf["keyboard"]["multiPressTimeout"]) / 1000.0
        except Exception:
            timeout = DOUBLE_PRESS_FALLBACK_SEC
        return min(max(timeout, DOUBLE_PRESS_MIN_SEC), DOUBLE_PRESS_MAX_SEC)

    @script(
        description=(
            "Read one of the last 10 Discord messages (Alt+1 newest ... Alt+0 10th);"
            " press the same key twice quickly to reply to that message"
        ),
        gestures=["kb:alt+%d" % n for n in range(1, 10)] + ["kb:alt+0"],
    )
    def script_readRecentMessage(self, gesture):
        key = gesture.mainKeyName
        index = KEY_TO_INDEX.get(key)
        if index is None:
            return
        # Track the key itself, not just the script. All ten gestures share one
        # script, so NVDA's getLastScriptRepeatCount() would read Alt+1 then a
        # quick Alt+2 as a repeat and reply to the wrong message.
        now = time.time()
        isRepeat = (key == self._lastReadKey
                    and now - self._lastReadTime <= self._doublePressTimeout())
        if isRepeat:
            self._lastReadKey = None  # a third press starts a fresh read
            self._lastReadTime = 0.0
            self._replyToMessage(index)
            return
        self._lastReadKey = key
        self._lastReadTime = now
        self._readMessage(index)

    # -----------------------------------------------------------------------
    # Reply to a message (double press of a read hotkey)
    # -----------------------------------------------------------------------

    def _authorOf(self, row):
        """Best-effort author name from a row, for the spoken confirmation.

        A row's text is "author , text , time", so the part before the first
        comma is the author. Only used for feedback - if the shape ever changes
        the worst case is a less specific confirmation, never a wrong action.
        """
        text = self._objectText(row)
        if not text:
            return ""
        # Phoenix prefixes replies: "Zack replying to UnboundDara , text , time".
        return text.split(",", 1)[0].split(" replying to ", 1)[0].strip()

    def _focusIsOn(self, target):
        """True if the system focus is on `target`.

        NVDA hands back a fresh NVDAObject per query, so `is` never matches;
        NVDAObject defines __eq__ for exactly this. Role+name is a backstop for
        the case where equality can't be established but it is plainly the same
        node, because the alternative - sending a bare "r" to whatever does have
        focus - would type a stray letter into the user's draft.
        """
        focus = self._safe(lambda: api.getFocusObject())
        if focus is None or target is None:
            return False
        try:
            if focus == target:
                return True
        except Exception:
            pass
        name = self._name(target)
        return bool(name) and self._role(focus) == self._role(target) and self._name(focus) == name

    @staticmethod
    def _looksLikeReplyControl(name):
        """True for Discord's Reply control, false for "Replying to ..." labels.

        A message that is itself a reply carries text starting "Replying to", and
        so does the composer bar. Matching those would click the wrong thing, so
        require the word "reply" exactly or as the start of a phrase like
        "Reply to Alice" - never the participle.
        """
        if not name:
            return False
        name = name.strip().lower()
        if name.startswith("replying"):
            return False
        return name == REPLY_CONTROL_NAME or name.startswith("reply ")

    def _findReplyControl(self, root, nodeCap, maxDepth):
        """Bounded DFS for an actionable object named "Reply". None if absent."""
        if root is None:
            return None
        stack = [(root, 0)]
        visited = 0
        while stack:
            obj, depth = stack.pop()
            visited += 1
            if visited > nodeCap:
                log.debug("Discord: reply-control search hit its node cap")
                return None
            if self._role(obj) in ACTION_ROLES and self._looksLikeReplyControl(self._name(obj)):
                return obj
            if depth < maxDepth:
                for ch in self._iterChildren(obj):
                    stack.append((ch, depth + 1))
        return None

    def _invoke(self, obj):
        """Press an object via its accessible default action. True if accepted."""
        try:
            obj.doAction()
            return True
        except Exception:
            log.debug("Discord: doAction failed on reply control", exc_info=True)
            return False

    def _replyToMessage(self, indexFromNewest):
        listObj = self._findMessagesList()
        if listObj is None:
            self._noMessagesHere("No messages here. Open a text channel or DM to reply.")
            return
        needed = indexFromNewest + 1
        messages = self._collectRecentMessages(listObj, needed)
        if len(messages) < needed:
            if not messages:
                self._cachedList = None
                ui.message("Couldn't read the messages. Try again, or run the debug dump command.")
            else:
                ui.message("Only %d messages are loaded." % len(messages))
            return
        row = messages[indexFromNewest]
        target = self._firstFocusable(row)
        if target is None:
            ui.message("Can't reply to that message; Discord is not offering it to the keyboard.")
            return
        author = self._authorOf(row)
        # Moving focus is the point of this command, exactly as with Alt+D - and
        # Discord only builds a message's action toolbar for the focused or
        # hovered message, so this is also what puts the Reply button in the tree.
        self._safe(lambda: target.setFocus())
        core.callLater(REPLY_FOCUS_DELAY_MS, self._pressReplyControl, row, target, author)

    def _pressReplyControl(self, row, target, author):
        """Second half of the reply: find Discord's Reply control and press it."""
        try:
            if not self._focusIsOn(target):
                ui.message("Couldn't select that message to reply to. Try again.")
                return
            # Cut the re-reading of the message we just spoke half a second ago.
            self._safe(lambda: speech.cancelSpeech())
            button = self._findReplyControl(row, REPLY_SUBTREE_NODE_CAP, REPLY_SUBTREE_MAX_DEPTH)
            if button is not None and self._invoke(button):
                core.callLater(REPLY_CONFIRM_DELAY_MS, self._confirmReply, author)
                return
            # No toolbar button: fall back to the message's context menu.
            log.debug("Discord: no Reply button on the row; trying the context menu")
            self._safe(lambda: KeyboardInputGesture.fromName("applications").send())
            core.callLater(REPLY_MENU_DELAY_MS, self._pressReplyMenuItem, author)
        except Exception:
            log.debug("Discord: reply step failed", exc_info=True)
            ui.message("Couldn't start a reply to that message.")

    def _pressReplyMenuItem(self, author):
        """Find "Reply" in the open context menu and press it.

        If it isn't there, close the menu again. Leaving a blind user parked in an
        open menu they did not ask for, with no announcement, is a worse outcome
        than the reply simply not happening.
        """
        try:
            menu = self._openMenuRoot()
            item = self._findReplyControl(menu, REPLY_MENU_NODE_CAP, REPLY_MENU_MAX_DEPTH)
            if item is not None and self._invoke(item):
                core.callLater(REPLY_CONFIRM_DELAY_MS, self._confirmReply, author)
                return
            self._safe(lambda: KeyboardInputGesture.fromName("escape").send())
            ui.message("Couldn't find Discord's reply command for that message.")
        except Exception:
            log.debug("Discord: reply menu step failed", exc_info=True)
            self._safe(lambda: KeyboardInputGesture.fromName("escape").send())
            ui.message("Couldn't start a reply to that message.")

    def _openMenuRoot(self):
        """Best root for searching the context menu Discord just opened.

        Focus normally moves into the menu, so walking up from it finds the menu
        container cheaply. If focus did not move, search the whole foreground -
        the menu is somewhere in it, and the node cap keeps that affordable.
        """
        node = self._safe(lambda: api.getFocusObject())
        steps = 0
        while node is not None and steps < ANCHOR_WALK_CAP:
            steps += 1
            role = self._role(node)
            if role == ROLE_POPUPMENU:
                return node
            node = self._safe(lambda n=node: n.parent)
        return self._safe(lambda: api.getForegroundObject())

    def _confirmReply(self, author):
        """Say whether the reply composer actually opened.

        Checked rather than assumed: if Discord ignores R the focus stays on the
        message, and a blind user typing their reply would have no way to notice
        that it was going nowhere.
        """
        try:
            focus = self._safe(lambda: api.getFocusObject())
            if focus is not None and self._role(focus) == ROLE_EDITABLETEXT:
                ui.message(("Replying to %s" % author) if author else "Replying")
            else:
                ui.message("Discord did not open a reply for that message.")
        except Exception:
            log.debug("Discord: reply confirmation failed", exc_info=True)

    # -----------------------------------------------------------------------
    # Jump to the "New messages" marker (first unread)
    # -----------------------------------------------------------------------

    def _isNewMarker(self, obj, role=None):
        """True if obj is Discord's unread divider (a SEPARATOR starting "new").

        Two forms seen in live dumps, both role=SEPARATOR:
            name='new'                    (unread marker on its own)
            name='new, 19 July, 2026'     (unread marker merged with a date)
        Plain date dividers are also SEPARATORs but start with a day number
        (e.g. "18 July, 2026"), so matching the leading word "new" is safe.
        """
        if role is None:
            role = self._role(obj)
        if role != ROLE_SEPARATOR:
            return False
        name = (self._name(obj) or "").strip().lower()
        return name == "new" or name.startswith("new,") or name.startswith("new ")

    def _firstFocusable(self, row):
        """Return a focusable object for a message row, or None.

        Discord message rows use a roving tabindex, so the row (or its inner
        ARTICLE) is programmatically focusable. Prefer the ARTICLE - focusing it
        lands the user right on the message body.
        """
        for cand in (self._findChildArticle(row), row):
            if cand is None:
                continue
            states = self._safe(lambda c=cand: c.states)
            if states and STATE_FOCUSABLE in states:
                return cand
        return None

    @script(
        description="Move focus to the first unread Discord message (the 'New messages' marker)",
        gesture="kb:alt+d",
    )
    def script_jumpToNewMessages(self, gesture):
        listObj = self._findMessagesList()
        if listObj is None:
            self._noMessagesHere("No messages here. Open a text channel or DM, then try again.")
            return
        # Walk newest-first (lastChild/previous, single cheap nav calls). The
        # unread messages come before the "new" marker; the last message row we
        # see before hitting the marker is the oldest unread = the first unread.
        node = self._safe(lambda: listObj.lastChild)
        firstUnread = None
        count = 0
        steps = 0
        marker = None
        while node is not None and steps < SIBLING_WALK_CAP:
            steps += 1
            role = self._role(node)
            if self._isNewMarker(node, role):
                marker = node
                break
            if role in MESSAGE_ROLES:
                count += 1
                firstUnread = node
                # Phoenix nests the divider inside the row as its first child,
                # so a row that opens with the marker is itself the first unread.
                if role == ROLE_LISTITEM:
                    first = self._safe(lambda n=node: n.firstChild)
                    if first is not None and self._isNewMarker(first):
                        marker = first
                        break
            node = self._safe(lambda n=node: n.previous)

        if marker is None:
            if steps >= SIBLING_WALK_CAP:
                ui.message("Couldn't find the new-messages marker; it may be scrolled out of view.")
            else:
                ui.message("No new messages in this channel.")
            return
        if firstUnread is None:
            ui.message("No new messages in this channel.")
            return

        # Move SYSTEM FOCUS to the first unread message. NVDA then reads the
        # newly focused message and the user is positioned there, so Discord's
        # own Up/Down arrows walk through the unread ones. (Unlike a read, this
        # is an explicit "take me there" - moving focus is the whole point.)
        target = self._firstFocusable(firstUnread)
        if target is not None:
            self._safe(lambda: target.setFocus())
            return
        # Not focusable (Discord changed its markup): fall back to moving the
        # review cursor and reading the message aloud, so the key still does
        # something useful.
        self._safe(lambda: api.setNavigatorObject(firstUnread))
        if steps >= SIBLING_WALK_CAP:
            label = "%d or more new messages" % count
        elif count == 1:
            label = "1 new message"
        else:
            label = "%d new messages" % count
        text = self._objectText(firstUnread)
        ui.message("%s. First: %s" % (label, text) if text else label)

    # -----------------------------------------------------------------------
    # Review the focused message in a read-only window
    # -----------------------------------------------------------------------

    def _browseModeCaretObject(self):
        """The object at the Phoenix browse mode caret, or None outside browse mode."""
        if _phoenixBrowseMode is None:
            return None
        focus = self._safe(lambda: api.getFocusObject())
        ti = getattr(focus, "treeInterceptor", None) if focus is not None else None
        if isinstance(ti, _phoenixBrowseMode.PhoenixBrowseDocument) and not ti.passThrough:
            return self._safe(ti.getCaretObject)
        return None

    def _focusedMessageRow(self):
        """The message row at the browse mode caret or the focus, or None if not on a message."""
        node = self._browseModeCaretObject() or self._safe(lambda: api.getFocusObject())
        child = None
        steps = 0
        while node is not None and steps < ANCHOR_WALK_CAP:
            steps += 1
            if self._listStillValid(node):
                return child  # the list's direct child = the row
            child = node
            node = self._safe(lambda n=node: n.parent)
        return None

    # Controls on a message that are actions, not content.
    VIEW_SKIP_NAMES = {"remove all embeds", "add reaction", "jump to reply",
                       "play", "open link", "wave to say hi!", "previous", "next"}
    # Toolbar Phoenix adds to the focused message (react / Reply / Forward / More).
    MESSAGE_ACTIONS_NAME = "message actions"
    VIEW_EMBED_NODE_CAP = 150

    def _messageParts(self, row):
        """Split a Phoenix message row into its parts, from its child objects.

        Body (GROUPING) children, per the 2026-11-08 dumps:
          BUTTON "Jump To Reply", BUTTON "@User", BUTTON "<quoted text>"  (replies)
          STATICTEXT header > BUTTON author, ..., STATICTEXT full date
          GROUPING "<message text, with line breaks>"
          GROUPING "" > LINK / BUTTON / STATICTEXT "" (one per line)     (embeds)
          BUTTON "Previous", BUTTON "Next"                     (paged embeds)
          GROUPING "Message Actions" > ...           (only on the focused row)
          TOGGLEBUTTON "thumbsup, 1 reaction, press to react"
          STATICTEXT "Edited Yesterday at 1:11 pm"
        """
        body = self._findChildArticle(row) or row
        p = {"author": "", "date": "", "reply": [], "text": "", "embed": [],
             "links": [], "attachments": [], "reactions": [], "notes": []}
        inReply = False
        for ch in self._iterChildren(body):
            role = self._role(ch)
            name = (self._name(ch) or "").strip()
            if role == ROLE_STATICTEXT:
                kids = list(self._iterChildren(ch))
                if kids and not p["author"] and self._role(kids[0]) == ROLE_BUTTON:
                    p["author"] = (self._name(kids[0]) or "").strip()
                    dates = [n for n in (self._name(k) for k in kids[1:]
                                         if self._role(k) == ROLE_STATICTEXT) if n]
                    p["date"] = dates[-1].strip() if dates else ""
                    inReply = False  # the header ends the reply context
                elif name and name.lower() not in self.VIEW_SKIP_NAMES:
                    p["notes"].append(name)
            elif role == ROLE_GROUPING:
                if name.lower() == self.MESSAGE_ACTIONS_NAME:
                    continue
                if name and not p["text"]:
                    p["text"] = name
                else:
                    self._collectEmbed(ch, p)
            elif role == ROLE_TOGGLEBUTTON:
                p["reactions"].append(name.replace(", press to react", ""))
            elif role == ROLE_BUTTON:
                if name.lower() == "jump to reply":
                    inReply = True
                elif inReply:
                    if name and not name.startswith("Server Tag:"):
                        p["reply"].append(name)
                elif name and name.lower() not in self.VIEW_SKIP_NAMES:
                    p["attachments"].append(name)
        # Continuation and system messages have no header: fall back to the
        # row's own name, "author , text , time".
        fields = (self._name(body) or "").split(" , ")
        if len(fields) >= 3:
            p["author"] = p["author"] or fields[0].split(" replying to ")[0].strip()
            p["date"] = p["date"] or fields[-1].strip()
            if not p["text"] and not p["embed"]:
                # shortcut: one run-on line when Discord exposes the embed's
                # lines only through this summary; upgrade if a dump shows them.
                p["text"] = " , ".join(fields[1:-1]).strip()
        elif not p["text"] and not p["embed"]:
            p["text"] = self._objectText(row)
        p["attachments"] = [a for a in p["attachments"] if a not in p["links"]]
        return p

    def _collectEmbed(self, root, p):
        """Gather link and button names from an embed grouping (bounded DFS)."""
        stack = [(root, 0)]
        visited = 0
        while stack and visited < self.VIEW_EMBED_NODE_CAP:
            obj, depth = stack.pop()
            visited += 1
            role = self._role(obj)
            name = (self._name(obj) or "").strip()
            if obj is not root and role == ROLE_LINK:
                if name and name not in p["links"]:
                    p["links"].append(name)
                continue
            if obj is not root and role == ROLE_BUTTON:
                if name and name.lower() not in self.VIEW_SKIP_NAMES and name not in p["attachments"]:
                    p["attachments"].append(name)
                continue
            if obj is not root and role == ROLE_STATICTEXT:
                # Embed lines have empty names; their text may be in value or text content.
                line = self._lineText(obj)
                if line:
                    p["embed"].append(line)
                continue
            if depth < 3:
                # Reversed so the stack pops children in document order.
                for ch in reversed(list(self._iterChildren(obj))):
                    stack.append((ch, depth + 1))

    def _lineText(self, obj):
        """Text of a text object: its name, else its value, else its text content."""
        return ((self._name(obj) or "").strip()
                or (self._safe(lambda: obj.value) or "").strip()
                or self._objectText(obj))

    @staticmethod
    def _messageHtml(p):
        e = html.escape
        out = []
        if p["author"]:
            out.append("<h1>%s</h1>" % e(p["author"]))
        if p["date"]:
            out.append("<p>%s</p>" % e(p["date"]))
        if p["reply"]:
            out.append("<p>Replying to %s</p>" % e(": ".join(p["reply"])))
        for para in p["text"].split("\n\n"):
            if para.strip():
                out.append("<p>%s</p>" % e(para.strip()).replace("\n", "<br>"))
        if p["embed"]:
            out.append("<h2>Embed</h2><p>%s</p>" % "<br>".join(e(x) for x in p["embed"]))
        for title, key in (("Links", "links"), ("Attachments", "attachments"),
                           ("Reactions", "reactions")):
            if p[key]:
                out.append("<h2>%s</h2><ul>%s</ul>"
                           % (title, "".join("<li>%s</li>" % e(x) for x in p[key])))
        for note in p["notes"]:
            out.append("<p>%s</p>" % e(note))
        return "\n".join(out)

    @script(
        description="Open the focused Discord message in a window where you can review it with the arrow keys",
        gesture="kb:alt+v",
    )
    def script_viewMessage(self, gesture):
        row = self._focusedMessageRow()
        if row is None:
            ui.message("Not on a message. Arrow to a message in the message list first.")
            return
        p = self._messageParts(row)
        if not (p["text"] or p["embed"] or p["links"] or p["attachments"]):
            ui.message("That message could not be read.")
            return
        title = "Message from %s" % p["author"] if p["author"] else "Discord message"
        # Browse mode in this window gives arrows, Ctrl+arrows, H for headings
        # and Escape to close.
        ui.browseableMessage(self._messageHtml(p), title, isHtml=True)

    # -----------------------------------------------------------------------
    # Jump to the server list / channel list
    # -----------------------------------------------------------------------
    #
    # Phoenix layout (dumps of 2026-11-08), all within a few levels of the window:
    #   GROUPING "Servers sidebar" > TREEVIEW > TREEVIEWITEM "Direct Messages",
    #       GROUPING "Servers" > TREEVIEWITEM "1 mention, A.K.I." ...
    #   GROUPING "<server> (server)" > LIST "Channels" > LISTITEM > LINK
    #       "sf6-links (text channel), Private Channel (locked)"
    #   GROUPING "Private channels" > LIST "Direct Messages" > LISTITEM > LINK
    #       "Orion (direct message), Idle" (after Friends / Nitro / Shop links)
    # The dumps carry no selected state, so "current" comes from the window
    # title: "#sf6-links | The World of Mischief - Discord".

    SIDEBAR_SEARCH_DEPTH = 4
    SIDEBAR_SEARCH_NODE_CAP = 600
    DM_LINK_MARKERS = ("(direct message)", "(group message)")

    def _titleParts(self):
        """(place, server) from the window title; server is "" outside a server."""
        title = self._name(self._safe(lambda: api.getForegroundObject())) or ""
        if title.endswith(" - Discord"):
            title = title[:-len(" - Discord")]
        place, _, server = title.partition(" | ")
        return place.strip().lstrip("#@").strip(), server.strip()

    @staticmethod
    def _nameMatches(name, target):
        """True if an item's name refers to `target`.

        Discord decorates names with comma-separated extras on either side
        ("1 mention, A.K.I.", "sf6-links (text channel), Private Channel").
        """
        if not name or not target:
            return False
        if name == target or name.startswith(target + ",") or name.startswith(target + " ("):
            return True
        return any(part == target or part.startswith(target + " (")
                   for part in name.split(", "))

    def _findInWindow(self, match, root=None, maxDepth=SIDEBAR_SEARCH_DEPTH):
        """Shallow bounded DFS from root (default: the foreground) for the first obj where match(obj, role)."""
        if root is None:
            root = self._safe(lambda: api.getForegroundObject())
        stack = [(root, 0)] if root is not None else []
        visited = 0
        while stack and visited < self.SIDEBAR_SEARCH_NODE_CAP:
            obj, depth = stack.pop()
            visited += 1
            role = self._role(obj)
            if match(obj, role):
                return obj
            # Lists and trees are targets, never containers of one: skip their rows.
            if depth < maxDepth and role not in (ROLE_LIST, ROLE_TREEVIEW):
                for ch in self._iterChildren(obj):
                    stack.append((ch, depth + 1))
        return None

    def _treeItems(self, node, depth=0):
        """Yield server-tree items in order, looking inside groupings and folders."""
        for ch in self._iterChildren(node):
            role = self._role(ch)
            if role == ROLE_TREEVIEWITEM:
                yield ch
                if depth < 2 and "folder" in (self._name(ch) or "").lower():
                    for item in self._treeItems(ch, depth + 1):
                        yield item
            elif role == ROLE_GROUPING and depth < 2:
                for item in self._treeItems(ch, depth + 1):
                    yield item

    def _listLinks(self, listObj):
        """Yield the first child (the channel/DM link or button) of each LISTITEM."""
        for row in self._iterChildren(listObj):
            if self._role(row) == ROLE_LISTITEM:
                child = self._safe(lambda r=row: r.firstChild)
                if child is not None:
                    yield child

    def _moveFocusTo(self, obj):
        states = self._safe(lambda: obj.states)
        if states and STATE_FOCUSABLE in states:
            self._safe(lambda: obj.setFocus())
            return
        # Not focusable: at least put the review cursor there and say where.
        self._safe(lambda: api.setNavigatorObject(obj))
        ui.message(self._name(obj) or "")

    # Age-restricted channels show a gate instead of the message list until you
    # confirm (dump of 2026-11-08): GROUPING "" > STATICTEXT "Age-Restricted
    # Channel", STATICTEXT "<explanation>", BUTTON "Go Back", BUTTON "Continue".
    AGE_GATE_TITLE = "Age-Restricted Channel"
    AGE_GATE_DEPTH = 3  # window > pane > gate grouping > title

    def _noMessagesHere(self, fallbackMessage):
        """Say why there are no messages: the age gate if it is up, else fallbackMessage."""
        title = self._findInWindow(
            lambda o, r: r == ROLE_STATICTEXT and self._name(o) == self.AGE_GATE_TITLE,
            maxDepth=self.AGE_GATE_DEPTH)
        if title is None:
            ui.message(fallbackMessage)
            return
        message = "This channel is age-restricted. Press Continue to view its messages."
        gate = self._safe(lambda: title.parent)
        for ch in (self._iterChildren(gate) if gate is not None else ()):
            if self._role(ch) == ROLE_BUTTON and self._name(ch) == "Continue":
                self._safe(lambda: ch.setFocus())
                # After the focus announcement, which would cancel speech queued earlier.
                core.callLater(REPLY_CONFIRM_DELAY_MS, ui.message, message)
                return
        ui.message(message)

    def _isFocusable(self, obj):
        states = self._safe(lambda: obj.states)
        return bool(states) and STATE_FOCUSABLE in states

    def _focusRow(self, row):
        """Focus a list row, or its first child when only that takes focus."""
        child = self._safe(lambda: row.firstChild)
        for cand in (row, child):
            if cand is not None and self._isFocusable(cand):
                self._safe(lambda c=cand: c.setFocus())
                return
        self._moveFocusTo(row)

    def _findNamedGrouping(self, name):
        return self._findInWindow(lambda o, r: r == ROLE_GROUPING and self._name(o) == name)

    # Friends page layout (dump of 2026-11-08):
    #   GROUPING "Friends" > PANE "Online — 23" > LIST "" > STATICTEXT header,
    #       LISTITEM > BUTTON "Open conversation with X", ...
    #   GROUPING "Active Now" > STATICTEXT "Active Now", BUTTON "Active Now" (one per card)
    # A channel or DM: GROUPING "<name> (channel)" > ..., EDITABLETEXT compose box
    # (named "You do not have permission ..." where you can't send).

    @script(
        description="Move focus to the user status and settings area at the bottom left of Discord",
        gesture="kb:control+shift+x",
    )
    def script_jumpToUserArea(self, gesture):
        # window > pane > GROUPING "User status and settings" > Voice Details, Disconnect, ..., Mute
        panel = self._findInWindow(
            lambda o, r: r == ROLE_GROUPING and self._name(o) == "User status and settings", maxDepth=2)
        if panel is None:
            ui.message("Couldn't find the user status and settings area.")
            return
        for ch in self._iterChildren(panel):
            if self._role(ch) in (ROLE_BUTTON, ROLE_TOGGLEBUTTON, ROLE_LINK) and self._name(ch):
                self._moveFocusTo(ch)
                return
        self._moveFocusTo(panel)

    @script(
        description="Move focus to the first person in Active Now on Discord's Friends page",
        gesture="kb:control+shift+a",
    )
    def script_jumpToActiveNow(self, gesture):
        panel = self._findNamedGrouping("Active Now")
        if panel is None:
            ui.message("Active Now is only on the Friends page, and only when the window is wide enough to show it.")
            return
        for ch in self._iterChildren(panel):
            if self._role(ch) == ROLE_BUTTON:
                self._moveFocusTo(ch)
                return
        ui.message("Nobody is active now.")

    @script(
        description="Move focus to the message box in a channel or DM, or to the first friend on the Friends page",
        gesture="kb:control+shift+z",
    )
    def script_jumpToComposeOrFriends(self, gesture):
        channel = self._findInWindow(self._isChannelAnchor, maxDepth=CHANNEL_SEARCH_DEPTH)
        if channel is not None:
            for ch in self._iterChildren(channel):
                if self._role(ch) == ROLE_EDITABLETEXT:
                    # Focusing it also announces "You do not have permission ..." where relevant.
                    self._moveFocusTo(ch)
                    return
            ui.message("This channel has no message box.")
            return
        # A voice channel with its chat closed: window > pane > BUTTON "Show Chat".
        showChat = self._findInWindow(
            lambda o, r: r == ROLE_BUTTON and self._name(o) == "Show Chat", maxDepth=2)
        if showChat is not None:
            self._moveFocusTo(showChat)
            return
        friends = self._findNamedGrouping("Friends")
        listObj = friends and self._findInWindow(lambda o, r: r == ROLE_LIST, root=friends)
        if not listObj:
            ui.message("No message box or friends list here.")
            return
        for row in self._iterChildren(listObj):
            if self._role(row) == ROLE_LISTITEM:
                self._focusRow(row)
                return
        ui.message("This friends list is empty.")

    @script(
        description="Move focus to the current server in Discord's server list",
        gesture="kb:control+shift+s",
    )
    def script_jumpToServerList(self, gesture):
        tree = self._findInWindow(lambda o, r: r == ROLE_TREEVIEW)
        if tree is None:
            ui.message("Couldn't find the server list.")
            return
        _, server = self._titleParts()
        first = None
        for item in self._treeItems(tree):
            if first is None:
                first = item  # "Direct Messages": the Home/Friends/DM position
            if server and self._nameMatches(self._name(item), server):
                self._moveFocusTo(item)
                return
        if first is None:
            ui.message("The server list is empty.")
            return
        self._moveFocusTo(first)

    @script(
        description="Move focus to the current channel in Discord's channel list, or the first direct message",
        gesture="kb:control+shift+c",
    )
    def script_jumpToChannelList(self, gesture):
        listObj = self._findInWindow(
            lambda o, r: r == ROLE_LIST and self._name(o) in ("Channels", "Direct Messages"))
        if listObj is None:
            ui.message("Couldn't find the channel list.")
            return
        isDMs = self._name(listObj) == "Direct Messages"
        place, _ = self._titleParts()
        # A voice channel's chat leaves the title on the last text channel.
        anchor = self._findInWindow(self._isChannelAnchor, maxDepth=CHANNEL_SEARCH_DEPTH)
        voicePrefix = "Text chat for voice channel "
        anchorName = (self._name(anchor) or "") if anchor is not None else ""
        if anchorName.startswith(voicePrefix):
            place = anchorName[len(voicePrefix):].strip()
        first = None
        for link in self._listLinks(listObj):
            name = self._name(link) or ""
            isConversation = not isDMs or any(m in name for m in self.DM_LINK_MARKERS)
            if not isConversation:
                continue  # Friends, Shop, Quests...: the "Friends" link must not match the title
            if first is None:
                first = link
            if self._nameMatches(name, place):
                self._moveFocusTo(link)
                return
        if first is None:
            ui.message("No direct messages." if isDMs else "The channel list is empty.")
            return
        self._moveFocusTo(first)

    # -----------------------------------------------------------------------
    # Auto-read incoming messages (event driven; opt-in via Alt+Shift+N)
    # -----------------------------------------------------------------------

    @script(
        description="Cycle auto-reading of new Discord messages: off, polite, interrupt",
        gesture="kb:alt+shift+n",
    )
    def script_cycleAutoRead(self, gesture):
        mode = (getAutoReadMode() + 1) % 3
        setAutoReadMode(mode)
        try:
            config.conf.save()  # persist immediately, matching the settings panel
        except Exception:
            log.debug("Discord: could not save auto-read mode", exc_info=True)
        # Turning it on: seed the "seen" set so we don't read the backlog that
        # is already on screen - only messages that arrive from now on.
        if mode != AUTO_OFF:
            self._primeAutoRead()
        ui.message(AUTO_MODE_NAMES.get(mode, "Auto-read"))

    def _primeAutoRead(self):
        """Remember the messages currently on screen as already-seen."""
        self._recentAnnounced.clear()
        listObj = self._findMessagesList()
        if listObj is None:
            self._autoReadPrimed = False
            return
        for obj in self._collectRecentMessages(listObj, NEWEST_ROW_SCAN):
            text = self._objectText(obj)
            if text:
                self._recentAnnounced.append(text)
        self._autoReadChannel = self._name(listObj)
        self._autoReadPrimed = True

    def _ancestorMessagesList(self, obj, maxUp=12):
        """Return the messages LIST that obj lives under, or None.

        A cheap bounded parent-walk - lets the show event handler ignore the
        vast majority of events (which happen outside the message list). One
        role read per hop; it stops early at anything the list never sits
        inside of: the "(channel)" grouping (we'd have passed the list already),
        a pane, or the window.
        """
        node = obj
        steps = 0
        while node is not None and steps < maxUp:
            steps += 1
            role = self._role(node)
            if self._listStillValid(node, role):
                return node
            if role in (ROLE_PANE, ROLE_WINDOW) or self._isChannelAnchor(node, role):
                return None
            node = self._safe(lambda n=node: n.parent)
        return None

    def event_show(self, obj, nextHandler):
        """Discord shows a new row when a message arrives; maybe announce it.

        Kept extremely cheap and fully guarded: auto-read is off by default, and
        even when on we bail immediately unless the shown object is inside the
        messages list. Never raises into NVDA's event dispatch.
        """
        try:
            self._maybeAnnounceNew(obj)
        except Exception:
            log.debug("Discord: auto-read event_show failed", exc_info=True)
        nextHandler()

    def _maybeAnnounceNew(self, shownObj):
        """Event path: only proceed if the shown object is in the message list."""
        if getAutoReadMode() == AUTO_OFF:
            return
        listObj = self._ancestorMessagesList(shownObj)
        if listObj is None:
            return
        self._cachedList = listObj
        self._announceNew(listObj)

    # -- polling fallback ---------------------------------------------------

    def _scheduleAutoPoll(self):
        # Re-decided every tick, so toggling Alt+Shift+N takes effect within one
        # interval without needing to touch the timer from anywhere else.
        interval = (AUTO_POLL_INTERVAL_MS if getAutoReadMode() != AUTO_OFF
                    else IDLE_POLL_INTERVAL_MS)
        try:
            self._pollTimer = wx.CallLater(interval, self._autoPollTick)
        except Exception:
            self._pollTimer = None

    def _autoPollTick(self):
        try:
            if self._discordIsForeground():
                # Warm the list cache even when auto-read is OFF. Discovered from
                # a user report: DMs were flaky with auto-read off but reliable
                # with it on. The reason was not auto-read itself - it was that
                # the poller kept _cachedList populated, so Alt+1 never had to run
                # a cold search. Warming unconditionally gives every user that
                # benefit. A tick with a valid cache is 2 COM calls (role + name);
                # a re-search is a shallow walk of a few dozen.
                listObj = self._pollListObj()
                if listObj is not None and getAutoReadMode() != AUTO_OFF:
                    self._announceNew(listObj)
        except Exception:
            log.debug("Discord: auto-read poll failed", exc_info=True)
        finally:
            self._scheduleAutoPoll()  # re-arm regardless

    def _discordIsForeground(self):
        fg = self._safe(lambda: api.getForegroundObject())
        return fg is not None and getattr(fg, "processID", None) == self.processID

    def _pollListObj(self):
        """Cached messages list; only run the costly search on a throttle."""
        if self._listStillValid(self._cachedList):
            return self._cachedList
        if time.time() - self._lastSearchTime < SEARCH_THROTTLE_SEC:
            return None
        self._lastSearchTime = time.time()
        self._cachedList = self._searchMessagesList()
        return self._cachedList

    # -- shared announce ----------------------------------------------------

    def _announceNew(self, listObj):
        """Speak any newly-arrived messages at the bottom of listObj.

        Shared by the event and poll paths. Primes (and stays quiet) the first
        time or after a channel switch, so a channel's existing backlog is never
        dumped - only messages that arrive afterwards.
        """
        mode = getAutoReadMode()
        if mode == AUTO_OFF:
            return
        if not self._autoReadPrimed or self._name(listObj) != self._autoReadChannel:
            self._primeAutoRead()
            return
        # Newest-first; stop at the first row we've already announced. Whatever
        # is above that stopping point is new (handles small bursts too).
        fresh = []
        sawRow = False
        for obj in self._iterMessageRows(listObj, NEWEST_ROW_SCAN):
            sawRow = True
            text = self._objectText(obj)
            if not text:
                continue
            if text in self._recentAnnounced:
                break
            fresh.append(text)
        if not sawRow:
            # The lazy walk deliberately has no "any row with text" fallback, so
            # if Discord ever changes the row role it would yield nothing and
            # auto-read would go silent - the one failure mode a blind user cannot
            # notice. Retry through the eager collector, which does have that
            # fallback. Only reachable when the fast path found no rows at all.
            for obj in self._collectRecentMessages(listObj, NEWEST_ROW_SCAN):
                text = self._objectText(obj)
                if not text:
                    continue
                if text in self._recentAnnounced:
                    break
                fresh.append(text)
        if not fresh:
            return
        # Speak oldest-first so the newest ends up last (and, in interrupt mode,
        # is the one left audible). Only the first announce interrupts; the rest
        # queue behind it so a burst reads in order.
        interrupt = (mode == AUTO_INTERRUPT)
        for i, text in enumerate(reversed(fresh)):
            self._recentAnnounced.append(text)
            self._announce(text, interrupt=(interrupt and i == 0))

    def _announce(self, text, interrupt):
        if interrupt:
            self._safe(lambda: speech.cancelSpeech())
        if Spri is not None:
            self._safe(lambda: speech.speakMessage(text, priority=Spri.NORMAL))
        else:
            self._safe(lambda: speech.speakMessage(text))
        try:
            braille.handler.message(text)
        except Exception:
            pass
        log.debug("Discord: auto-read announced: %r" % text[:80])

    # -----------------------------------------------------------------------
    # Debug: dump structure to a file in Downloads (uses safe navigation)
    # -----------------------------------------------------------------------

    @script(
        description="Discord debug: save a structure dump to the Downloads folder",
        # Deliberately awkward: the dump writes message text to disk, so it must
        # not be reachable by a slip of the hand. Rebindable in Input Gestures.
        gesture="kb:NVDA+control+shift+f10",
    )
    def script_debugDump(self, gesture):
        path = os.path.join(self._downloadsDir(), "discord_nvda_dump.txt")
        try:
            lines = []
            lists = []
            fg = api.getForegroundObject()
            self._collectTree(fg, 0, lines, lists)
            with open(path, "w", encoding="utf-8") as f:
                f.write("Discord NVDA structure dump\n")
                f.write("Generated: %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                f.write("Foreground: role=%r name=%r\n" % (self._role(fg), self._name(fg)))
                f.write("MESSAGES_LIST_NAME_PREFIX = %r\n\n" % MESSAGES_LIST_NAME_PREFIX)

                f.write("=== LIST objects found: %d ===\n\n" % len(lists))
                for i, lst in enumerate(lists):
                    f.write("--- LIST #%d  name=%r ---\n" % (i + 1, self._name(lst)))
                    shown = 0
                    # Walk children via lastChild/previous (newest first), safe.
                    node = self._safe(lambda l=lst: l.lastChild)
                    steps = 0
                    while node is not None and shown < 12 and steps < SIBLING_WALK_CAP:
                        steps += 1
                        snippet = self._objectText(node)[:150].replace("\n", " ")
                        f.write("    row role=%r name=%r text=%r\n"
                                % (self._role(node), self._name(node), snippet))
                        shown += 1
                        node = self._safe(lambda n=node: n.previous)
                    f.write("\n")

                # The focused object in detail. This is what tells us whether
                # Discord has built a Reply control for the selected message:
                # take a dump with a message focused (Alt+D, or a double press)
                # and this section shows the row's toolbar, or its absence.
                f.write("=== FOCUSED OBJECT ===\n")
                focus = self._safe(lambda: api.getFocusObject())
                if focus is None:
                    f.write("  (no focus object)\n\n")
                else:
                    f.write("  focus: role=%r name=%r\n" % (self._role(focus), self._name(focus)))
                    f.write("  ancestry (focus outward):\n")
                    node = self._safe(lambda: focus.parent)
                    hops = 0
                    while node is not None and hops < ANCHOR_WALK_CAP:
                        hops += 1
                        f.write("    ^%d role=%r name=%r\n"
                                % (hops, self._role(node), self._name(node)))
                        node = self._safe(lambda n=node: n.parent)
                    root = self._safe(lambda: focus.parent) or focus
                    subtree = []
                    self._collectTree(root, 0, subtree, [])
                    f.write("  subtree around focus (%d nodes):\n" % len(subtree))
                    for line in subtree[:REPLY_SUBTREE_NODE_CAP]:
                        f.write("    %s\n" % line)
                    f.write("\n")

                self._dumpBrowseDocument(f)

                f.write("=== FULL TREE (role / name, depth-limited) ===\n")
                f.write("\n".join(lines))
                f.write("\n")
            ui.message("Discord structure dump saved to your Downloads folder as discord_nvda_dump.txt")
            log.info("Discord dump written to %s" % path)
        except Exception as e:
            log.error("Discord dump failed", exc_info=True)
            ui.message("Could not save the dump: %s" % e)

    @script(
        description=(
            "Discord self-check: test what the add-on relies on in the new (Phoenix) client,"
            " and save a report to the Downloads folder"
        ),
        gesture="kb:NVDA+control+shift+f11",
    )
    def script_phoenixSelfCheck(self, gesture):
        if _phoenixBrowseMode is None or _phoenixChecks is None:
            ui.message("The self-check is not available in this NVDA version.")
            return
        import ctypes
        import winUser
        hwnd = self._safe(lambda: api.getForegroundObject().windowHandle)
        if not hwnd or winUser.getClassName(hwnd) != _phoenixChecks.WINDOW_CLASS:
            hwnd = ctypes.windll.user32.FindWindowW(_phoenixChecks.WINDOW_CLASS, None)
        if not hwnd:
            ui.message("The new Discord client is not running, so there is nothing to check.")
            return
        try:
            raw = _phoenixBrowseMode.fetchRaw(hwnd)
            checks = _phoenixChecks.runChecks(raw, winUser.getClassName(hwnd))
            text = _phoenixChecks.report(checks, "Discord Phoenix self-check, %s\nWindow: %s"
                                         % (time.strftime("%Y-%m-%d %H:%M:%S"), raw.name))
            path = os.path.join(self._downloadsDir(), "discord_phoenix_check.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception as e:
            log.error("Discord: Phoenix self-check failed", exc_info=True)
            ui.message("The self-check could not run: %s" % e)
            return
        # The report holds no message text, only structure - though it does name
        # the open channel or DM and the window title.
        ui.message("Self-check: %s. Report saved to Downloads as discord_phoenix_check.txt"
                   % _phoenixChecks.spokenSummary(checks))

    BROWSE_DUMP_LINE_CAP = 400

    def _dumpBrowseDocument(self, f):
        """The Phoenix browse mode document as rendered: each line and its fields."""
        if _phoenixBrowseMode is None:
            return
        focus = self._safe(lambda: api.getFocusObject())
        ti = getattr(focus, "treeInterceptor", None) if focus is not None else None
        if not isinstance(ti, _phoenixBrowseMode.PhoenixBrowseDocument):
            return
        buf = ti._buffer
        f.write("=== PHOENIX BROWSE MODE DOCUMENT ===\n")
        if buf is None:
            f.write("  (not loaded)\n\n")
            return
        f.write("  passThrough=%r  lines=%d  chars=%d  caret=%r\n"
                % (ti.passThrough, len(buf.lineStarts), len(buf.text), ti._selectionOffsets))
        for i, start in enumerate(buf.lineStarts[:self.BROWSE_DUMP_LINE_CAP]):
            end = buf.lineStarts[i + 1] if i + 1 < len(buf.lineStarts) else len(buf.text)
            fields = " > ".join(
                n.role + ("[%s]" % n.landmark if n.landmark else "")
                for n in buf.fieldChain(start))
            f.write("  %4d %r  | %s\n" % (i, buf.text[start:end].rstrip("\n"), fields))
        f.write("\n")

    def _collectTree(self, obj, depth, lines, lists):
        if obj is None or len(lines) > SEARCH_NODE_CAP:
            return
        role = self._role(obj)
        if role is None:
            return
        name = self._name(obj)
        line = "%s%r  %r" % ("  " * depth, role, name)
        if not name and role == ROLE_STATICTEXT:
            # Phoenix embeds keep their text off the name; show where it is.
            text = self._lineText(obj)
            if text:
                line += "  text=%r" % text
        lines.append(line)
        if role == ROLE_LIST:
            lists.append(obj)
        if depth >= SEARCH_MAX_DEPTH:
            return
        for ch in self._iterChildren(obj):
            self._collectTree(ch, depth + 1, lines, lists)

    @staticmethod
    def _downloadsDir():
        home = os.path.expanduser("~")
        downloads = os.path.join(home, "Downloads")
        return downloads if os.path.isdir(downloads) else home
