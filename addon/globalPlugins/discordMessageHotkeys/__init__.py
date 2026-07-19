# -*- coding: utf-8 -*-
# Discord Message Hotkeys - settings panel.
#
# Adds a "Discord Message Hotkeys" category to NVDA's Settings dialog with one
# control: the default mode for auto-reading new messages. It shares a single
# config key with the app module's Alt+Shift+N hotkey, so the two always agree.
#
# This lives in a global plugin (not the app module) because NVDA's settings
# categories must be registered once at startup, regardless of which app is
# focused.

import config
import globalPluginHandler
import gui
import wx
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel, NVDASettingsDialog

# Kept in step with addon/appModules/discord.py (same section + key).
CONFIG_SECTION = "discordMessageHotkeys"
CONFIG_KEY_MODE = "autoReadMode"
config.conf.spec[CONFIG_SECTION] = {
    CONFIG_KEY_MODE: "integer(default=0, min=0, max=2)",
}

# Index matches the mode integers: 0 off, 1 polite, 2 interrupt.
MODE_LABELS = [
    _("Off"),
    _("Polite (wait for current speech to finish)"),
    _("Interrupt (speak the new message immediately)"),
]


class DiscordMessageHotkeysPanel(SettingsPanel):
    # Translators: the title of this add-on's category in NVDA Settings.
    title = _("Discord Message Hotkeys")

    def makeSettings(self, settingsSizer):
        helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
        # Translators: label for the auto-read mode chooser.
        self.modeChoice = helper.addLabeledControl(
            _("Auto-read new messages in the open channel:"),
            wx.Choice,
            choices=MODE_LABELS,
        )
        try:
            current = int(config.conf[CONFIG_SECTION][CONFIG_KEY_MODE])
        except Exception:
            current = 0
        if current < 0 or current >= len(MODE_LABELS):
            current = 0
        self.modeChoice.SetSelection(current)

    def onSave(self):
        config.conf[CONFIG_SECTION][CONFIG_KEY_MODE] = self.modeChoice.GetSelection()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    def __init__(self, *args, **kwargs):
        super(GlobalPlugin, self).__init__(*args, **kwargs)
        NVDASettingsDialog.categoryClasses.append(DiscordMessageHotkeysPanel)

    def terminate(self, *args, **kwargs):
        try:
            NVDASettingsDialog.categoryClasses.remove(DiscordMessageHotkeysPanel)
        except ValueError:
            pass
        super(GlobalPlugin, self).terminate(*args, **kwargs)
