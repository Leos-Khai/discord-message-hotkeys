# -*- coding: utf-8 -*-
# Discord Message Hotkeys - NVDA app module for the Discord desktop client.
#
#   Alt+1  -> newest message   ...   Alt+9 -> 9th newest   Alt+0 -> 10th newest
#   Alt+D  -> move focus to the "New messages" marker (first unread message)
#   Alt+Shift+N -> cycle auto-reading of new messages: off / polite / interrupt
#   Alt+Shift+D -> write a structure dump to the Downloads folder (debug)
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

import os
import time
from collections import deque
import wx
import appModuleHandler
import api
import ui
import config
import speech
import braille
import controlTypes
import textInfos
from scriptHandler import script
from logHandler import log

# Speech priorities let us distinguish "polite" (queue after current speech)
# from "interrupt" (speak right now). Available on all supported NVDA versions,
# but guard the import so an API change can't stop the module loading.
try:
    from speech.priorities import Spri
except Exception:  # pragma: no cover - very old/very new NVDA
    Spri = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_MESSAGES = 10

# Case-insensitive prefix of the messages-list accessible name.
# Confirmed from a live dump: "Messages in sf6-links".
MESSAGES_LIST_NAME_PREFIX = "messages"

# Safety caps so nothing can freeze NVDA.
SEARCH_NODE_CAP = 15000     # max objects visited while locating the list
SEARCH_MAX_DEPTH = 45       # max descent depth while locating the list
SEARCH_TIME_BUDGET = 0.6    # max wall-clock seconds for one list search.
#   This is the real anti-lag guard: on a non-channel screen (Friends, Home,
#   Settings) there is no "Messages in..." list, so the search would otherwise
#   walk the whole tree (~15000 COM round-trips = the ~5s hang). The budget
#   makes it give up in well under a second and warn instead.
SIBLING_WALK_CAP = 250      # max rows to step through when collecting messages
CHILD_ITER_CAP = 600        # max children to iterate for any one node

# Roles: enum on modern NVDA (2022.1+), constants on older. Support both.
try:
    ROLE_LIST = controlTypes.Role.LIST
    ROLE_LISTITEM = controlTypes.Role.LISTITEM
    ROLE_ARTICLE = controlTypes.Role.ARTICLE
    ROLE_SEPARATOR = controlTypes.Role.SEPARATOR
    STATE_FOCUSABLE = controlTypes.State.FOCUSABLE
except AttributeError:
    ROLE_LIST = controlTypes.ROLE_LIST
    ROLE_LISTITEM = controlTypes.ROLE_LISTITEM
    ROLE_ARTICLE = controlTypes.ROLE_ARTICLE
    ROLE_SEPARATOR = controlTypes.ROLE_SEPARATOR
    STATE_FOCUSABLE = controlTypes.STATE_FOCUSABLE

MESSAGE_ROLES = {ROLE_LISTITEM, ROLE_ARTICLE}

# "1".."9" -> 0..8 (count back from newest); "0" -> 9 (10th newest).
KEY_TO_INDEX = {str(n): n - 1 for n in range(1, 10)}
KEY_TO_INDEX["0"] = 9

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
config.conf.spec[CONFIG_SECTION] = {
    CONFIG_KEY_MODE: "integer(default=0, min=0, max=2)",
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
# Don't re-run the (potentially costly) full list search from the poller more
# often than this when there is no valid cached list, e.g. on a non-channel
# screen. On an open channel the cached list stays valid, so no search happens.
SEARCH_THROTTLE_SEC = 3.0


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

    # -----------------------------------------------------------------------
    # Small safe helpers (single COM calls, with a light retry)
    # -----------------------------------------------------------------------

    @staticmethod
    def _safe(func, retries=2):
        """Call func(), tolerating transient COM errors like CallCancelled."""
        for attempt in range(retries + 1):
            try:
                return func()
            except Exception:
                if attempt < retries:
                    time.sleep(0.02)
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

    def _listStillValid(self, obj):
        if obj is None:
            return False
        name = self._name(obj)
        return (
            self._role(obj) == ROLE_LIST
            and name
            and name.lower().startswith(MESSAGES_LIST_NAME_PREFIX)
        )

    def _findMessagesList(self):
        if self._listStillValid(self._cachedList):
            return self._cachedList
        self._cachedList = self._searchMessagesList()
        return self._cachedList

    def _searchMessagesList(self):
        """Bounded depth-first search for the messages LIST (no bulk fetches)."""
        fg = api.getForegroundObject()
        if fg is None:
            return None
        deadline = time.time() + SEARCH_TIME_BUDGET
        stack = [(fg, 0)]
        visited = 0
        while stack:
            obj, depth = stack.pop()
            visited += 1
            if visited > SEARCH_NODE_CAP:
                log.debug("Discord: search hit node cap without finding the list")
                return None
            # Wall-clock guard: on a non-channel screen there is no messages
            # list, so bail fast instead of walking the whole tree (the ~5s lag).
            if time.time() > deadline:
                log.debug("Discord: search exceeded time budget without finding the list")
                return None
            role = self._role(obj)
            if role == ROLE_LIST:
                name = self._name(obj)
                if name and name.lower().startswith(MESSAGES_LIST_NAME_PREFIX):
                    return obj
            if depth < SEARCH_MAX_DEPTH:
                for ch in self._iterChildren(obj):
                    stack.append((ch, depth + 1))
        return None

    # -----------------------------------------------------------------------
    # Collect recent messages WITHOUT a bulk children fetch
    # -----------------------------------------------------------------------

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
        """Return obj's child ARTICLE (the message body), if any.

        A Discord message row is a LISTITEM whose single child is an ARTICLE
        whose accessible NAME is the whole message ("author , text , time").
        One cheap firstChild/next walk - no bulk fetch.
        """
        for ch in self._iterChildren(obj):
            if self._role(ch) == ROLE_ARTICLE:
                return ch
        return None

    def _objectText(self, obj):
        # The row itself (a LISTITEM) has no useful text: makeTextInfo returns
        # only U+FFFC placeholders standing in for its child ARTICLE. Read the
        # ARTICLE, whose accessible name carries the full message.
        if self._role(obj) != ROLE_ARTICLE:
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
            ui.message("No messages here. Open a text channel or DM to read messages.")
            return
        needed = indexFromNewest + 1
        messages = self._collectRecentMessages(listObj, needed)
        if len(messages) < needed:
            if not messages:
                # List was found but rows couldn't be read - drop the cache so
                # the next press re-locates a fresh list object.
                self._cachedList = None
                ui.message("Couldn't read the messages. Try again, or run Alt+Shift+D.")
            else:
                ui.message("Only %d messages are loaded." % len(messages))
            return
        text = self._objectText(messages[indexFromNewest])  # newest-first
        ui.message(text if text else "Message %d could not be read." % needed)

    # -----------------------------------------------------------------------
    # Read commands
    # -----------------------------------------------------------------------

    @script(
        description="Read one of the last 10 Discord messages (Alt+1 newest ... Alt+0 10th)",
        gestures=["kb:alt+%d" % n for n in range(1, 10)] + ["kb:alt+0"],
    )
    def script_readRecentMessage(self, gesture):
        index = KEY_TO_INDEX.get(gesture.mainKeyName)
        if index is not None:
            self._readMessage(index)

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
            ui.message("No messages here. Open a text channel or DM, then try again.")
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
        vast majority of events (which happen outside the message list).
        """
        node = obj
        steps = 0
        while node is not None and steps < maxUp:
            steps += 1
            if self._listStillValid(node):
                return node
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
        try:
            self._pollTimer = wx.CallLater(AUTO_POLL_INTERVAL_MS, self._autoPollTick)
        except Exception:
            self._pollTimer = None

    def _autoPollTick(self):
        try:
            if getAutoReadMode() != AUTO_OFF and self._discordIsForeground():
                listObj = self._pollListObj()
                if listObj is not None:
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
        gesture="kb:alt+shift+d",
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

                f.write("=== FULL TREE (role / name, depth-limited) ===\n")
                f.write("\n".join(lines))
                f.write("\n")
            ui.message("Discord structure dump saved to your Downloads folder as discord_nvda_dump.txt")
            log.info("Discord dump written to %s" % path)
        except Exception as e:
            log.error("Discord dump failed", exc_info=True)
            ui.message("Could not save the dump: %s" % e)

    def _collectTree(self, obj, depth, lines, lists):
        if obj is None or len(lines) > SEARCH_NODE_CAP:
            return
        role = self._role(obj)
        if role is None:
            return
        lines.append("%s%r  %r" % ("  " * depth, role, self._name(obj)))
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
