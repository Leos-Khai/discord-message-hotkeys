# Guideline: Build an NVDA Add-on that Reads the Last 10 Discord Messages with Alt+1 – Alt+0

This document is written **for Claude Code** (or any developer) to implement and finish an NVDA add-on for the **Discord desktop client on Windows 11**. It explains the goal, the underlying technology, exactly how NVDA can find Discord's messages, the traps to avoid, and a step-by-step build/test/verify workflow. A working code skeleton ships alongside this file (`addon/appModules/discord.py` and `addon/manifest.ini`); this guideline tells you how it works and what to confirm or refine.

---

## 1. The goal

Add ten keyboard commands to NVDA that work while the Discord desktop app is in the foreground:

| Key | Action |
|-----|--------|
| Alt+1 | Read the **newest** (most recent) message in the current channel |
| Alt+2 | Read the 2nd newest message |
| Alt+3 … Alt+9 | Read the 3rd … 9th newest message |
| Alt+0 | Read the **10th** newest message |
| Alt+Shift+D | Debug: dump the message tree to the NVDA log (development aid) |

"Read" means: speak the message through NVDA (author, text, timestamp — whatever NVDA can extract), **without moving the user's focus or cursor**. The user should be able to be typing in the message box, press Alt+3, hear the 3rd-newest message, and keep typing.

The add-on must **not** try to drive or automate NVDA itself. It runs *inside* NVDA as a plug-in and uses NVDA's own Python API to read the screen and speak.

---

## 2. Background: why this is even possible

Understanding two facts up front prevents most dead ends.

### 2.1 Discord is a web page in a desktop wrapper

The Discord desktop client is built with **Electron**, which means the entire UI is **Chromium** (the engine behind Chrome) rendering a web app. There is no traditional native Win32 UI. Everything you "see" is HTML with ARIA accessibility attributes.

Consequences:

- NVDA reads Discord through the **IAccessible2 (IA2)** accessibility API that Chromium exposes — the same path NVDA uses for Chrome/Edge web pages.
- Discord's UI is organized with **ARIA landmarks, roles, and labels**. The interface has six landmark regions: server sidebar, channel list, user area, channel header, the **channel (message) area**, and the members list. The messages live in the channel area.
- Because it is a web document, NVDA treats it with **browse mode** (virtual buffer) and **focus mode**, exactly like a website.

### 2.2 The message list is a labelled ARIA list

Inside the channel area, Discord renders the messages as a **list**. Its accessible name (from `aria-label`) is of the form **"Messages in `<channel-name>`"**. Each message row is a **list item** (some builds expose it as an **article**). The newest message is the **last** child in the list; the oldest loaded message is the first.

This is the anchor the whole add-on is built on: *find the object with role LIST whose name starts with "Messages", then read its children.*

> ⚠️ **Do not treat the exact markup as gospel.** Discord ships UI changes frequently. Roles ("list item" vs "article") and the exact label wording can change. That is why the skeleton includes a **discovery/debug command (Alt+Shift+D)** — always confirm the live structure before trusting hardcoded selectors. See Section 5.

---

## 3. How NVDA finds and reads messages (the mechanism)

NVDA represents everything on screen as a tree of **NVDAObjects**. Each object has properties such as `role`, `name` (its accessible label), `states`, `parent`, `children`, `firstChild`, `next`, etc. Your code walks this tree.

The add-on's read path is four steps:

1. **Get the foreground window.**
   `api.getForegroundObject()` returns the top NVDAObject for the app currently in front (Discord).

2. **Find the messages list.**
   Iterate `foreground.recursiveDescendants` (a depth-first generator over every descendant object) and return the first object where:
   - `obj.role == controlTypes.Role.LIST`, **and**
   - `obj.name` starts (case-insensitively) with `"messages"`.

3. **Collect the message rows.**
   Take the list's children whose role is LIST ITEM or ARTICLE. That list is **oldest-first**, so `children[-1]` is the newest.

4. **Extract the text of the chosen row and speak it.**
   The most reliable way to get a message's full text (author + body + timestamp, across nested elements) is a **TextInfo**:
   ```python
   info = obj.makeTextInfo(textInfos.POSITION_ALL)
   text = info.text
   ```
   `POSITION_ALL` spans the entire object and its descendants, so it captures the rendered text even when it is split across many child elements. If that ever returns empty, fall back to `obj.name` (the aria-label). Speak the result with `ui.message(text)` — this announces text through NVDA **without** moving focus or the review cursor.

### Why `makeTextInfo` instead of reading `obj.name` directly?

A message row's `name` may be only a partial label (or empty), because the visible content lives in child elements. `makeTextInfo(POSITION_ALL).text` flattens all of that into one string, which is what a human hears when they arrow onto the message. It is the closest match to "what NVDA would say if you navigated there."

### Why walk the object tree instead of the browse-mode virtual buffer?

You *could* read the virtual buffer (the browse-mode document, a "tree interceptor"). But object navigation via `api.getForegroundObject()` + `recursiveDescendants` works the same whether the user is in **browse mode or focus mode** and whether or not their cursor is in the message box. That robustness is exactly what we want for global hotkeys. Keep to object navigation.

---

## 4. Critical constraints and gotchas (read before coding)

These are the things that will bite an implementer who assumes Discord behaves like a static page.

1. **The list is virtualized.** Chromium/Discord only keeps the messages currently scrolled into view in the DOM/accessibility tree. Messages far above the viewport are **not present as objects**. So "the last 10 messages" really means *"the last 10 currently rendered,"* which in practice is the newest ones when the channel is scrolled to the bottom (the default). If fewer than 10 are loaded, read what exists and tell the user how many were found. Do **not** try to force-scroll the channel to hydrate more messages in v1 — it moves the user's position and fights NVDA. Document the limitation instead.

2. **Consecutive messages from the same author are grouped.** Discord visually groups back-to-back messages from one person. Depending on the build, a "row" (list item) may correspond to a single message *or* a grouped block. During discovery (Section 5), check whether each list-item child equals one message or a group, and note it. For v1, treating each child row as "one message" is acceptable and matches how NVDA arrow-navigation steps through them.

3. **Key-conflict check.** Discord's own shortcuts use **Ctrl+1…9** to jump to servers, and Ctrl+Alt+arrows to move between servers/unread channels — **not** Alt+1…0. So Alt+number is largely free inside Discord, which is why it is a good choice. Still verify on the target machine that no other NVDA add-on or global command claims Alt+1…0. Because the commands are registered with a `scriptCategory`, the user can rebind them in **NVDA menu → Preferences → Input Gestures → "Discord Message Hotkeys"** if a conflict appears.

4. **Number-key detection.** Bind all ten gestures to a **single** script and branch on `gesture.mainKeyName` (which is `"1"`…`"9"`, `"0"`). This is cleaner and less error-prone than ten near-identical methods. The skeleton does this.

5. **App-module naming is not optional.** NVDA auto-loads an app module only if the file name matches the process executable's base name. Discord's process is `Discord.exe`, so the file **must** be `appModules/discord.py` and define a class named `AppModule`. A different name silently never loads.

6. **Role API differs by NVDA version.** Modern NVDA (2022.1+) uses the enum `controlTypes.Role.LIST`; older versions used the constant `controlTypes.ROLE_LIST`. The skeleton tries the enum and falls back to the constant, so it works across versions. Keep that shim.

7. **Never block NVDA's main thread.** Scripts run on NVDA's core thread. Keep the tree walk cheap: stop at the first matching list, and only enumerate that list's direct children (do **not** deep-scan the entire Discord tree on every key press). If a full-tree scan is ever slow on a big server, cache the found list object and re-validate it, or narrow the search by first locating the channel-area landmark.

---

## 5. Discovery-first workflow (do this before trusting selectors)

Because Discord's markup can drift, confirm the real structure on the actual machine **before** finalizing the selectors. This is what the `Alt+Shift+D` debug command is for, and it can be done two ways.

### Option A — the built-in debug command

With the skeleton installed and a Discord channel open, press **Alt+Shift+D**. It writes to the NVDA log:
- whether a "Messages" list was found, its `name` and `role`, and
- for each child row: its `role`, `name`, and the first 120 characters of extracted text.

Open the log via **NVDA menu → Tools → View log** (or set log level to Debug in NVDA's Advanced settings). Confirm that:
- a LIST named like `"Messages in …"` is found,
- its children have role LIST ITEM (or ARTICLE), and
- the extracted text matches the actual messages, newest last.

If the list is **not** found, the command dumps the foreground tree (roles + names, five levels deep) so you can see the real role/label of the message container and update `MESSAGES_LIST_NAME_PREFIX` / `MESSAGE_ROLES` accordingly.

### Option B — NVDA Python Console (interactive)

Enable the console (NVDA Advanced settings) and open it with **NVDA+Ctrl+Z** while Discord is focused, then explore live:
```python
import api, controlTypes, textInfos
fg = api.getForegroundObject()
# Find the messages list:
lst = next(o for o in fg.recursiveDescendants
           if o.role == controlTypes.Role.LIST
           and o.name and o.name.lower().startswith("messages"))
print(lst.name, lst.role)
rows = [c for c in lst.children]
print(len(rows), "rows")
for c in rows[-3:]:                      # last 3 (newest)
    print(c.role, repr(c.name))
    print(repr(c.makeTextInfo(textInfos.POSITION_ALL).text))
```
This confirms — with real data — the label wording, the row role, whether a row is one message or a group, and that `makeTextInfo` returns clean text. **Update the constants in `discord.py` to match whatever you observe.**

---

## 6. Add-on structure

```
addon/
├── manifest.ini              # add-on metadata (name, version, NVDA compat)
└── appModules/
    └── discord.py            # the AppModule: gestures + read logic + debug
```

- **`manifest.ini`** — declares the add-on name, version, and the minimum/last-tested NVDA versions. NVDA reads this at load time.
- **`appModules/discord.py`** — auto-loaded when `Discord.exe` is in front. Defines `class AppModule(appModuleHandler.AppModule)` with:
  - `scriptCategory` so the commands appear grouped and remappable in Input Gestures.
  - `_findMessagesList()`, `_getMessages()`, `_objectText()`, `_readMessage()` — the four-step read path from Section 3.
  - `script_readRecentMessage` bound to Alt+1…Alt+0, branching on `gesture.mainKeyName`.
  - `script_debugDump` bound to Alt+Shift+D.

A packaged NVDA add-on (`.nvda-addon`) is simply this `addon/` folder's **contents** zipped up with `manifest.ini` at the **root** of the archive, then given the `.nvda-addon` extension.

---

## 7. Build, install, and test

### 7.1 Fast iteration via the scratchpad (recommended while developing)

You do not need to repackage the add-on on every change.

1. In NVDA: **Preferences → Settings → Advanced**, check **"Enable loading custom code from Developer Scratchpad Directory."**
2. Open the scratchpad: **NVDA menu → Tools → (open the scratchpad / user config folder)**. The path is typically
   `%APPDATA%\nvda\scratchpad\`.
3. Copy `discord.py` to `…\scratchpad\appModules\discord.py`.
4. Reload plug-ins with **NVDA+Ctrl+F3** (or restart NVDA).
5. Open Discord, open a channel, and test Alt+1…Alt+0 and Alt+Shift+D.

### 7.2 Package as a `.nvda-addon` (for real installs / sharing)

From the `addon/` directory, zip its **contents** (not the folder itself) so `manifest.ini` sits at the archive root, then rename the `.zip` to `.nvda-addon`. Example (PowerShell):
```powershell
Compress-Archive -Path .\addon\* -DestinationPath .\discordMessageHotkeys.zip
Rename-Item .\discordMessageHotkeys.zip discordMessageHotkeys.nvda-addon
```
Install by opening the `.nvda-addon` file (NVDA will prompt) or via **NVDA menu → Tools → Add-on Store → Install from external source**. Restart NVDA when prompted.

> A pre-built `discordMessageHotkeys.nvda-addon` is provided alongside this guideline so it can be installed and tested immediately.

### 7.3 Acceptance tests (what "done" looks like)

- With a Discord channel open and several messages present, **Alt+1** speaks the newest message; **Alt+2** the one before it; **Alt+0** the 10th newest.
- Pressing a key when **fewer than N** messages are loaded speaks a graceful "Only X messages are loaded" rather than erroring.
- Pressing a key with **no channel open** (e.g. the friends screen) speaks "No messages found. Open a channel first."
- Focus/caret **does not move** when reading — verify by typing in the message box, reading a message, and confirming the text cursor is unchanged.
- **Alt+Shift+D** writes a readable tree dump to the NVDA log.
- The commands appear under **Input Gestures → "Discord Message Hotkeys"** and can be rebound.

---

## 8. Refinements to consider after v1 works

- **Prefix each readout** with its position, e.g. "3rd newest: …", so the user knows which key landed. (Optional; some users prefer just the message.)
- **Distinguish author vs body**: if discovery shows author and content as separate child objects, you can read them in a chosen order or let the user configure it.
- **Configurable count / mapping** via an add-on settings panel (`gui.settingsDialogs`), so the user can change which key reads what.
- **Handle grouped messages** precisely once discovery clarifies whether a row is one message or a group.
- **Braille**: `ui.message` already routes to braille as well as speech; verify it reads well on a display.
- **Localization**: wrap user-facing strings in `_()` and ship translations if desired.

---

## 9. Reference for the implementer

- **NVDA Developer Guide** (app modules, global plugins, scripts, gestures, `scriptCategory`): https://download.nvaccess.org/documentation/developerGuide.html
- **NVDA Add-on Development Guide (community)**: https://github.com/nvdaaddons/DevGuide/wiki/NVDA-Add-on-Development-Guide
- **NVDAObjects API** (roles, `children`, `recursiveDescendants`, `makeTextInfo`): https://www.webbie.org.uk/nvda/api/NVDAObjects.NVDAObject-class.html
- **`api` module** (`getForegroundObject`, `getFocusObject`): https://www.webbie.org.uk/nvda/api/api-module.html
- **NVDA source (appModule examples)**: https://github.com/nvaccess/nvda/tree/master/source/appModules
- **Discord + NVDA usage guide** (interface landmarks, how the app is navigated): https://github.com/PepperTheVixen/Discord-With-NVDA
- **Discord keyboard shortcuts** (confirm no Alt+number conflicts): https://support.discord.com/hc/en-us/articles/225977308--Windows-Discord-Hotkeys

---

### One-paragraph summary for a hurried reader

Discord is an Electron/Chromium web app; NVDA reads it as a web document. The messages are an ARIA **list** named "Messages in `<channel>`", each message a **list item**, newest last. The add-on is an NVDA **app module** named `discord.py` (must match `Discord.exe`). On each Alt+number key it: gets the foreground object, finds the "Messages" list among its descendants, takes the child *N* back from the end, extracts that row's text with `makeTextInfo(POSITION_ALL)`, and speaks it with `ui.message` — never moving focus. The list is **virtualized**, so only currently-rendered messages exist; read what's there and report the count. Confirm the live roles/labels with the **Alt+Shift+D** debug dump or the **NVDA Python Console** before trusting the selectors, because Discord's markup changes over time.
