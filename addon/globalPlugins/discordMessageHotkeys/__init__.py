# -*- coding: utf-8 -*-
# Discord Message Hotkeys - settings panel.
#
# Adds a "Discord Message Hotkeys" category to NVDA's Settings dialog: the
# default mode for auto-reading new messages (shared with the app module's
# Alt+Shift+N hotkey, so the two always agree), and whether the new Phoenix
# client gets a browse mode document.
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

# Kept in step with addon/appModules/discord.py (same section + keys). Both
# assign the whole spec, so both must list every key.
CONFIG_SECTION = "discordMessageHotkeys"
CONFIG_KEY_MODE = "autoReadMode"
CONFIG_KEY_BROWSE_MODE = "phoenixBrowseMode"
config.conf.spec[CONFIG_SECTION] = {
    CONFIG_KEY_MODE: "integer(default=0, min=0, max=2)",
    CONFIG_KEY_BROWSE_MODE: "boolean(default=True)",
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
        # Translators: label for the checkbox that turns on browse mode in the new
        # (Rust "Phoenix") Discord client, which NVDA cannot browse by itself.
        self.browseModeCheck = helper.addItem(
            wx.CheckBox(self, label=_("Use &browse mode in the new Discord client (Phoenix)")))
        try:
            browse = bool(config.conf[CONFIG_SECTION][CONFIG_KEY_BROWSE_MODE])
        except Exception:
            browse = True
        self.browseModeCheck.SetValue(browse)

    def onSave(self):
        config.conf[CONFIG_SECTION][CONFIG_KEY_MODE] = self.modeChoice.GetSelection()
        config.conf[CONFIG_SECTION][CONFIG_KEY_BROWSE_MODE] = self.browseModeCheck.GetValue()


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
