# Changelog

All notable changes to this add-on are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

The release workflow reads the section matching the version in
`addon/manifest.ini` and publishes it as the GitHub Release notes, so **a
version with no section here will fail the release build**. Write the entry in
the same commit that bumps the version.

## [Unreleased]

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

[Unreleased]: https://github.com/Leos-Khai/discord-message-hotkeys/compare/v0.7.1...HEAD
[0.7.1]: https://github.com/Leos-Khai/discord-message-hotkeys/releases/tag/v0.7.1
[0.7.0]: https://github.com/Leos-Khai/discord-message-hotkeys/releases/tag/v0.7.0
[0.6.1]: https://github.com/Leos-Khai/discord-message-hotkeys/releases/tag/v0.6.1
[0.5.1]: https://github.com/Leos-Khai/discord-message-hotkeys/releases/tag/v0.5.1
