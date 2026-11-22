# discord-message-hotkeys
Add alt+keys for various discord actions

## Development

The add-on gives Discord's new Rust ("Phoenix") client a browse mode, built
from its UI Automation tree. Three things keep that working as Discord changes:

- **`python -m unittest discover -s tests`** runs on every push (CI). The
  tests rebuild every screen type recorded from the live client, with made-up
  names, and check how each reads, its landmarks, the NVDA side against
  stand-ins for NVDA, and that the self-check notices when Discord moves things.
- **NVDA+Ctrl+Shift+F11** in Discord checks the open screen live and saves a
  report to Downloads. `tools/phoenix_check.py` runs the same checks from a
  terminal, without NVDA.
- **`tools/phoenix_tour.py`** visits every kind of screen in the running
  client (Friends tabs, DMs, channels, a forum and its thread, Discover,
  Quests, Shop, Nitro, Message Requests, Settings, Inbox) and checks each one.
  Run it after a Discord update. It only opens things; it skips voice and stage
  channels and marks the channels it opens as read. With `--server "<a server
  you own for testing>"` it also covers that server's voice channel (joining
  and leaving it), stage, Members, Browse Channels, Server Boosts, Events,
  server menu, Server Settings, Channel Settings and channel popups;
  `--server-only` skips the rest.

The tools need Windows, Python 3 and `pip install comtypes`. When Discord's
tree changes, update the shapes in `tests/phoenix_fixtures.py` together with
the fix.
