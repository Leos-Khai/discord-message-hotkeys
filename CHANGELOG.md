# Changelog

All notable changes to this add-on are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

The release workflow reads the section matching the version in
`addon/manifest.ini` and publishes it as the GitHub Release notes, so **a
version with no section here will fail the release build**. Write the entry in
the same commit that bumps the version.

## [Unreleased]

### Added

- **Browse mode in the new Rust "Phoenix" client.** Phoenix is not a web page,
  so NVDA gave it no browse mode at all. The add-on now builds one from the
  client's accessibility tree: arrow through messages (each one reads "author,
  time", then what it replies to and the message line by line), use quick navigation
  keys (H moves message by message; K, B, F, E, L, I, S; D for the
  sections F6 moves between: top bar, server list, channel list, user area,
  channel header, the page or conversation, and the member list or profile
  panel), NVDA+F7, find,
  and Enter to open DMs, links, servers and tabs. Friends, members, DMs and
  activity cards are one line each, and repeated labels, server tags and
  tooltips don't clutter the reading. Moving up past the oldest loaded message
  loads older ones, as in the Electron client, without moving the mouse.
- **NVDA+Ctrl+Shift+F11 checks the new client after a Discord update.** It
  tests everything browse mode relies on in the open window (regions, the
  message list, how messages and replies are built, the member list, the
  Friends page, and the rendered document), says how many checks passed and
  which failed, and saves a report to the Downloads folder. It keeps up with Discord while you
  read, without moving you off the message you are on. NVDA+F5 refreshes it,
  Alt+V reads the message at the browse mode cursor, and it can be turned off
  in the add-on's settings.
- **Alt+V opens the focused message in a read-only window,** where you can read
  it by line, word or character. Escape closes it.
- **Ctrl+Shift+Z jumps to the message box** in the open channel or DM, or to the
  first friend on the Friends page.
- **Ctrl+Shift+A jumps to the first person in Active Now** on the Friends page.
- **Ctrl+Shift+X jumps to the user status and settings area** at the bottom
  left: voice details, Disconnect, your profile, Mute, Deafen and settings.
- **Ctrl+Shift+S jumps to the server list,** landing on the server you are in, or
  on Direct Messages from the Friends page or a DM.
- **Ctrl+Shift+C jumps to the channel list,** landing on the channel you are in.
  Outside a server it goes to the direct messages list: the open conversation,
  or the first direct message from the Friends page.

### Fixed

- **Voice channel chat works.** Discord names that conversation "Text chat for
  voice channel …" rather than "… (channel)", so the reading hotkeys, Alt+D,
  reply, auto-read and Ctrl+Shift+Z did not find it. Ctrl+Shift+C now lands on
  the voice channel, not the last text channel left in the window title. With
  the chat closed, Ctrl+Shift+Z moves to the Show Chat button.
- **Keys keep working with the member list open.** The member list's area is
  also named "… (channel)", and the add-on could take it for the conversation.
- **Ctrl+Shift+C on the Friends page lands on the first direct message,** not
  the Friends link above the list.
- **Faster, and no more false "No messages here" after using the sidebars.**
  Finding the message list used to fall back to a slow, time-limited search of
  the whole window whenever focus was outside the conversation, for example
  after Ctrl+Shift+S or Ctrl+Shift+C. That search could give up before finding
  the list. It is now a short walk to the conversation, so it is quick from
  anywhere. The background check no longer pauses NVDA every few seconds on the
  Friends and Settings screens, failed lookups are no longer retried, and the
  auto-read event check stops sooner.
- **Age-restricted channels no longer report "No messages here".** Until you
  confirm the 18+ notice, Discord shows that notice instead of the messages. The
  reading hotkeys, reply and Alt+D now say so and move focus to its Continue
  button.
- **Works with Discord's new Rust "Phoenix" client.** The new client wraps the
  conversation in a grouping rather than a landmark, puts each message's text on
  a grouping rather than an article, and places date and "New messages" dividers
  inside the message row. The hotkeys, Alt+D and auto-read now recognise both
  the old and the new layout.

## [0.9.0] - 2026-07-28

### Added

- **Press a reading hotkey twice quickly to reply to that message.** Alt+1 Alt+1
  replies to the newest message, Alt+3 Alt+3 to the third newest, and so on for
  every key from Alt+1 to Alt+0. The add-on selects the message, asks Discord to
  reply to it, and confirms with "Replying to" and the author's name, leaving you
  in the compose box with the reply attached.

  The gap allowed between the two presses is NVDA's own multi-press timeout —
  half a second by default — so it matches the timing of every other double-press
  command you already use.

  A single press behaves exactly as before and still does not move your focus.
  The second press does move focus, deliberately, in the same way Alt+D does: a
  reply has to be attached to a message Discord considers selected.

  Each step is checked rather than assumed. If the message cannot be selected,
  or Discord's reply command cannot be found, or the reply does not open, the
  add-on says so — rather than leaving you typing an answer that is going
  nowhere.

### Changed

- The debug dump now includes a section describing the focused object, its
  ancestors, and the tree around it. Taking a dump while a message is focused
  shows exactly which controls Discord has built for that message, which is the
  fastest way to diagnose a command that has stopped working.

## [0.8.1] - 2026-07-21

Fixes direct messages intermittently reporting "No messages here" when they were
open and full of messages. No gestures changed.

### Fixed

- **Alt+1 through Alt+0 and Alt+D now work reliably in direct messages.** They
  would sometimes report "No messages here. Open a text channel or DM to read
  messages." in a DM that was plainly open, then work on the next attempt.

  The 0.6 second limit on searching for the message list, added in 0.6.1 to stop
  the add-on hanging on the Friends and Home screens, was too tight. Finding the
  list from a standing start takes roughly 500 calls into Discord, and when
  Discord is busy those calls slow down enough to cross the limit — so the search
  gave up and reported an empty channel. Whether it crossed the line varied from
  press to press, which is why the fault came and went.

  Anyone who found that turning on auto-read with Alt+Shift+N made the problem
  mostly disappear was seeing this too: auto-read's background timer kept the
  message list cached, so the hotkeys were skipping the search rather than
  succeeding at it.

### Changed

- The add-on now finds the message list by starting from where you are focused
  and looking outward to the surrounding conversation area, instead of searching
  the whole Discord window from the top. This takes about a quarter as many calls
  into Discord, so the search is much less likely to run out of time. If Discord
  changes its layout, the add-on falls back to the old whole-window search.

- A key press now gets up to 2 seconds to find the message list, while background
  checks keep the tighter 0.6 second limit. When you press a key you are waiting
  on purpose and would rather wait a moment than be told a DM is empty. This
  longer limit applies only inside a conversation; see below.

- The message list is now kept ready in the background whether or not auto-read
  is switched on, so the first hotkey press after opening a channel no longer
  pays for the search. Previously only auto-read users got this.

- The Friends, Home, and Settings screens are now detected by the absence of a
  conversation area around your focus, rather than by waiting for a search to run
  out of time. On those screens the hotkeys give up after 0.35 seconds instead of
  the previous 0.6, so the "no messages here" warning comes back sooner.

- Reduced the background work the add-on does while Discord is open. When
  auto-read is off it now checks every 5 seconds instead of every 1.5, and each
  check normally inspects one message instead of six — roughly 20 calls into
  Discord per minute, down from about 500.

## [0.8.0] - 2026-07-20

### Changed

- **The debug dump command has moved from Alt+Shift+D to NVDA+Ctrl+Shift+F10.**
  Alt+Shift+D was easy to hit by accident, and the command writes the text of
  on-screen messages to a file in Downloads, so an accidental press wrote
  private conversation to disk without the user meaning to. The new gesture is
  deliberately awkward.

  If you had already assigned your own key to this command, your assignment is
  unaffected. If you were using the default, it has changed; you can set it back
  under Preferences, then Input Gestures, in the Discord Message Hotkeys
  category.

- The error message shown when messages cannot be read no longer names a
  specific key for the dump command, so it stays correct if the command is
  rebound.

## [0.7.1] - 2026-07-20

Groundwork for submitting the add-on to the NVDA Add-on Store. No functional
changes: hotkey behavior is identical to 0.7.0.

### Added

- A user guide at `addon/doc/en/readme.html`. The manifest's `docFileName` has
  always pointed at this file, but it did not exist, so the Help button in
  NVDA's Add-ons Manager had nothing to open.

### Fixed

- The manifest's `url` field was empty; it now points at the source repository.
  The Add-on Store requires it, and it must be HTTPS.

## [0.7.0] - 2026-07-20

No functional changes to the add-on: hotkey behavior is identical to 0.6.1. This
release exists to publish the add-on through the new automated pipeline.

### Added

- Releases are now built and published automatically from `main`, driven by the
  version in `addon/manifest.ini`.
- Each release ships a SHA-256 checksum file and a signed build provenance
  attestation, so a download can be verified against what CI actually built.
- This changelog, which now supplies the release notes.

## [0.6.1] - 2026-07-19

Version 0.6.0 was a local intermediate build that was never committed
separately; its changes are folded into this entry.

### Added

- Alt+Shift+N cycles auto-reading of incoming messages in the open channel
  through three modes: off, polite (waits for current speech to finish), and
  interrupt (speaks immediately).
- A "Discord Message Hotkeys" category in NVDA's Settings dialog for setting the
  default auto-read mode. It shares one config key with the Alt+Shift+N hotkey,
  so the two always agree.

## [0.5.1] - 2026-07-19

Initial commit of the repository. Versions at and below 0.5.1 were developed
before this repository existed and have no recoverable per-version history; the
feature set at 0.5.1 was:

- Alt+1 (newest) through Alt+0 (10th newest) read recent messages in the current
  Discord channel without moving focus or the caret.
- Alt+D moves focus to the first unread message (the "New messages" marker).
- Alt+Shift+D saves an accessibility-tree dump to the Downloads folder for
  debugging.
- Bounded, time-limited, and cached message-list search so the add-on cannot
  freeze NVDA. Outside a channel the hotkeys warn quickly instead of hanging.

[Unreleased]: https://github.com/Leos-Khai/discord-message-hotkeys/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/Leos-Khai/discord-message-hotkeys/releases/tag/v0.9.0
[0.8.1]: https://github.com/Leos-Khai/discord-message-hotkeys/releases/tag/v0.8.1
[0.8.0]: https://github.com/Leos-Khai/discord-message-hotkeys/releases/tag/v0.8.0
[0.7.1]: https://github.com/Leos-Khai/discord-message-hotkeys/releases/tag/v0.7.1
[0.7.0]: https://github.com/Leos-Khai/discord-message-hotkeys/releases/tag/v0.7.0
[0.6.1]: https://github.com/Leos-Khai/discord-message-hotkeys/releases/tag/v0.6.1
[0.5.1]: https://github.com/Leos-Khai/discord-message-hotkeys/releases/tag/v0.5.1
