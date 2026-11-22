# -*- coding: utf-8 -*-
"""How Phoenix browse mode reads, and that the self-check catches Discord changes.

Run: python -m unittest discover -s tests -v
"""
import unittest

import phoenix_fixtures as fx
import _phoenixBuffer as pb
import _phoenixChecks as pc


def failures(checks):
    return [c for c in checks if c.status in (pc.FAIL, pc.WARN)]


class ChannelReading(unittest.TestCase):

    def setUp(self):
        self.buf = pb.build(fx.channelScreen())
        self.lines = fx.lines(self.buf)

    def after(self, line, count):
        i = self.lines.index(line)
        return self.lines[i:i + count]

    def test_message_reads_heading_then_text(self):
        self.assertEqual(self.after("Ann, 18/11/2026 7:03 am", 3),
                         ["Ann, 18/11/2026 7:03 am", "hello there", "lizard, 1 reaction, press to react"])

    def test_follow_on_message_gets_its_own_heading(self):
        self.assertEqual(self.after("Ann, 7:04 am", 2), ["Ann, 7:04 am", "second line of thought"])

    def test_reply_quote_comes_before_the_message(self):
        self.assertEqual(self.after("Bob, 18/11/2026 8:11 am", 3),
                         ["Bob, 18/11/2026 8:11 am", "Replying to @Ann: hello there", "6 7!"])

    def test_multi_line_message_keeps_its_lines_in_order(self):
        self.assertEqual(self.after("Cat, 8:49 am", 4), ["Cat, 8:49 am", "line one", "line two", "line three"])

    def test_every_message_heading_is_level_3(self):
        headings = [n for n in self.buf.nodes if n.role == "heading" and n.level == 3
                    and pb.isMessageBody(n.parent.raw)]
        self.assertEqual([n.label for n in headings],
                         ["Ann, 18/11/2026 7:03 am", "Ann, 7:04 am", "Bob, 18/11/2026 8:11 am", "Cat, 8:49 am"])

    def test_reply_line_is_the_jump_button(self):
        node = self.buf.nodeAt(self.buf.text.index("Replying to @Ann"))
        self.assertEqual((node.role, node.raw.name), ("button", "Jump To Reply"))

    def test_no_server_tags_header_parts_or_window_buttons(self):
        for unwanted in ("Server Tag", "Wednesday, 18 November", "Minimize", "Maximize", "Close",
                         "Resize Sidebar", "Text icon"):
            self.assertNotIn(unwanted, self.buf.text)

    def test_composer_tooltips_become_descriptions(self):
        self.assertNotIn("Upgrade your friends", self.lines)
        gift = self.buf.nodeAt(self.buf.text.index("Send a gift"))
        self.assertTrue(gift.description.startswith("Upgrade your friends"))

    def test_member_line_puts_display_name_first(self):
        self.assertIn("Jo, jo_user, Online, Playing Game", self.lines)
        self.assertNotIn("— 1", self.buf.text)

    def test_landmarks_follow_f6_sections(self):
        found = [(n.fieldName, n.landmark) for n in self.buf.nodes if n.landmark]
        self.assertEqual(found, [
            ("Top bar", "banner"), ("Servers sidebar", "navigation"),
            ("Server One (server)", "navigation"), ("User status and settings", "region"),
            ("Channel header", "region"), ("general (channel)", "main"),
            ("Members list for general (channel)", "complementary"),
        ])

    def test_self_check_passes(self):
        self.assertEqual(failures(pc.runChecks(fx.channelScreen(), pc.WINDOW_CLASS)), [])


class FormattedMessages(unittest.TestCase):

    def setUp(self):
        self.buf = pb.build(fx.formattedScreen())
        self.lines = fx.lines(self.buf)

    def after(self, line, count):
        i = self.lines.index(line)
        return self.lines[i:i + count]

    def test_code_block_lines_are_separate_then_copy(self):
        self.assertEqual(self.after("Ann, 12:07 pm", 5),
                         ["Ann, 12:07 pm", "Code block:", "line one", "line two", "Copy"])

    def test_quote_is_a_block_quote_without_markers(self):
        self.assertEqual(self.after("a quote", 3), ["a quote", "more quote", "after"])
        self.assertEqual(self.buf.nodeAt(self.buf.text.index("more quote")).role, "blockQuote")

    def test_message_heading_is_a_heading_at_its_level(self):
        node = self.buf.nodeAt(self.buf.text.index("Smaller heading"))
        self.assertEqual((node.role, node.level, node.isField), ("heading", 2, True))

    def test_heading_and_list_items_each_on_their_own_line(self):
        self.assertEqual(self.after("Smaller heading", 3), ["Smaller heading", "bullet one", "1. first"])
        item = self.buf.nodeAt(self.buf.text.index("1. first"))
        self.assertEqual((item.role, item.parent.role), ("listItem", "list"))

    def test_server_reply_names_its_author_then_the_quote(self):
        self.assertEqual(self.after("Bob, 12:12 pm", 3),
                         ["Bob, 12:12 pm", "Replying to @Ann: Code block: line one line two", "a server reply"])

    def test_plain_message_unchanged(self):
        self.assertEqual(self.after("Ann, 12:09 pm", 2), ["Ann, 12:09 pm", "just text"])

    def test_mentions_stay_in_the_line(self):
        self.assertEqual(self.after("Cy, 12:20 pm", 2), ["Cy, 12:20 pm", "@Ann @Bob swap roles"])

    def test_unnamed_text_runs_read_from_the_summary(self):
        self.assertIn("The 7 with old says: one", self.lines)
        self.assertNotIn("says", self.lines)

    def test_edited_message_says_edited_once(self):
        self.assertIn("fixed it (edited)", self.lines)
        self.assertNotIn("Edited Today at 12:23 pm", self.lines)

    def test_thread_button_follows_the_text(self):
        self.assertEqual(self.after("start here", 2), ["start here", "Thread Plans 1 Message ›"])

    def test_inbox_author_is_not_the_role_icon(self):
        buf = pb.build(fx.inboxRoleIconScreen())
        self.assertIn("Dee, 10:09 am", fx.lines(buf))

    def test_spoilers_have_no_lines_of_their_own(self):
        self.assertEqual([n for n in self.buf.nodes if pb.isHiddenSpoiler(n.raw)], [])
        self.assertEqual(self.after("Cy, 12:25 pm", 3), ["Cy, 12:25 pm", "Spoiler", "Cy, 12:26 pm"])
        self.assertEqual(self.after("a Spoiler b Spoiler", 2)[1], "Cy, 12:24 pm")

    def test_link_beside_a_spoiler_keeps_its_line(self):
        self.assertEqual(self.after("Spoiler Spoiler and a link https://example.com/", 2)[1],
                         "https://example.com/")

    def test_hover_toolbar_left_out(self):
        self.assertNotIn("Click to react with thumbsup", self.lines)
        self.assertEqual(self.after("just text", 2)[1], "Bob, 12:12 pm")

    def test_self_check_passes(self):
        self.assertEqual(failures(pc.runChecks(fx.formattedScreen(), pc.WINDOW_CLASS)), [])


class FriendsReading(unittest.TestCase):

    def setUp(self):
        self.lines = fx.lines(pb.build(fx.friendsScreen()))

    def test_friend_is_one_line_then_its_buttons(self):
        i = self.lines.index("Sam, sam1234, Idle")
        self.assertEqual(self.lines[i:i + 3], ["Sam, sam1234, Idle", "Message Sam", "More options for Sam"])

    def test_dm_status_said_once(self):
        self.assertIn("Alex (direct message), Online, alex_user", self.lines)

    def test_repeated_game_profile_buttons_merged(self):
        self.assertEqual(self.lines.count("View Game Profile"), 0)
        self.assertEqual(self.lines.count("View Game Profile, Game – 2h"), 1)

    def test_self_check_passes(self):
        self.assertEqual(failures(pc.runChecks(fx.friendsScreen(), pc.WINDOW_CLASS)), [])


def landmarks(buf):
    return [(n.fieldName, n.landmark) for n in buf.nodes if n.landmark]


class EveryScreen(unittest.TestCase):
    """Each screen recorded live is recognised, passes its checks, and reads well."""

    SCREENS = [
        ("channel", fx.channelScreen, {}),
        ("announcement", fx.announcementScreen, {}),
        ("forum", fx.forumScreen, {}),
        ("forum", fx.forumScreen, {"withThread": True}),
        ("dm", fx.dmScreen, {}),
        ("groupDm", fx.dmScreen, {"group_": True}),
        ("friends", fx.friendsScreen, {}),
        ("discover", fx.discoverScreen, {}),
        ("quests", fx.questsScreen, {}),
        ("shop", fx.shopScreen, {}),
        ("nitro", fx.nitroScreen, {}),
        ("messageRequests", fx.messageRequestsScreen, {}),
        ("settings", fx.settingsScreen, {}),
        ("profile", fx.profileScreen, {}),
        ("profile", fx.profileCardScreen, {}),
        ("inbox", fx.inboxScreen, {}),
        ("menu", fx.contextMenuScreen, {}),
        ("voice", fx.voiceScreen, {}),
        ("voiceChat", fx.voiceScreen, {"withChat": True}),
        ("stage", fx.stageScreen, {}),
        ("stage", fx.stageScreen, {"withChat": True}),
        ("serverSettings", fx.serverSettingsScreen, {}),
        ("channelSettings", fx.channelSettingsScreen, {}),
        ("modal", fx.pinnedPopupScreen, {}),
        ("events", fx.eventsScreen, {}),
        ("serverMembers", fx.serverMembersScreen, {}),
        ("browseChannels", fx.browseChannelsScreen, {}),
        ("serverBoosts", fx.serverBoostsScreen, {}),
    ]

    def test_building_does_not_change_the_tree(self):
        # The self-check reads the same tree after building it; a second build
        # (a refresh) must read the same.
        for kind, make, kw in self.SCREENS:
            with self.subTest(screen=kind, **kw):
                raw = make(**kw)
                first = pb.build(raw).text
                self.assertEqual(pc.detectScreen(raw).kind, kind)
                self.assertEqual(pb.build(raw).text, first)

    def test_nameless_call_buttons_take_their_label(self):
        buf = pb.build(fx.voiceScreen())
        for label, role in (("Turn On Camera", "toggleButton"), ("Share Your Screen", "toggleButton"),
                            ("Start An Activity", "button")):
            node = buf.nodeAt(buf.text.index(label))
            self.assertEqual((node.label, node.role), (label, role))

    def test_call_text_chats_are_the_conversation(self):
        for make in (fx.voiceScreen, fx.stageScreen):
            with self.subTest(make=make.__name__):
                found = landmarks(pb.build(make(withChat=True)))
                self.assertTrue(any(l == "main" and n.startswith("Text chat for ") for n, l in found), found)

    def test_settings_sidebars_are_navigation(self):
        self.assertIn(("Server settings pages", "navigation"), landmarks(pb.build(fx.serverSettingsScreen())))
        self.assertIn(("Settings pages", "navigation"), landmarks(pb.build(fx.channelSettingsScreen())))
        self.assertEqual([n for n, l in landmarks(pb.build(fx.serverSettingsScreen())) if l == "main"],
                         ["Server Settings"])

    def test_popup_over_a_page_is_a_region(self):
        found = landmarks(pb.build(fx.pinnedPopupScreen()))
        self.assertIn(("Pinned Messages", "region"), found)
        self.assertEqual([n for n, l in found if l == "main"], ["general (channel)"])
    # A context menu is not a page: NVDA uses focus mode in it, and it has no landmarks.
    WITHOUT_MAIN = ("menu",)

    def test_each_screen_is_recognised_and_passes(self):
        for kind, make, kw in self.SCREENS:
            with self.subTest(screen=kind, **kw):
                raw = make(**kw)
                self.assertEqual(pc.detectScreen(raw).kind, kind)
                self.assertEqual(failures(pc.runChecks(raw, pc.WINDOW_CLASS)), [])

    def test_each_screen_has_one_main_landmark(self):
        for kind, make, kw in self.SCREENS:
            with self.subTest(screen=kind, **kw):
                mains = [n for n, l in landmarks(pb.build(make(**kw))) if l == "main"]
                self.assertEqual(len(mains), 0 if kind in self.WITHOUT_MAIN else 1, mains)

    def test_inbox_mentions_read_like_messages(self):
        lines = fx.lines(pb.build(fx.inboxScreen()))
        i = lines.index("Kim, 7:10 am")
        self.assertEqual(lines[i:i + 2], ["Kim, 7:10 am", "ping @Me"])

    def test_context_menu_reactions_drop_shortcodes(self):
        lines = fx.lines(pb.build(fx.contextMenuScreen()))
        self.assertEqual(lines[0], "Add Reaction: thumbsup")
        self.assertIn("Reply", lines)

    def test_profile_card_reads_bio_and_roles(self):
        lines = fx.lines(pb.build(fx.profileCardScreen()))
        self.assertIn("Hello there.", lines)
        self.assertIn("Remove role Mods", lines)

    def test_settings_reads_each_option_once(self):
        buf = pb.build(fx.settingsScreen())
        lines = fx.lines(buf)
        i = lines.index("Enable Desktop Notifications")
        self.assertEqual(lines[i:i + 2], ["Enable Desktop Notifications", "Shows notifications on your desktop."])
        self.assertEqual(lines.count("Enable Desktop Notifications"), 1)
        self.assertIn("Someone reacts to my messages, All Messages", lines)
        self.assertEqual(buf.nodeAt(buf.text.index("Enable Desktop")).role, "toggleButton")
        self.assertEqual(lines.count("Notifications"), 2)  # its tab in the sidebar, and the page heading
        self.assertNotIn("Breadcrumb", lines)

    def test_settings_landmarks(self):
        # The breadcrumb only repeats the page heading, so it is left out.
        self.assertEqual(landmarks(pb.build(fx.settingsScreen())),
                         [("Settings", "main"), ("Settings sidebar", "navigation")])

    def test_profile_is_one_landmark_and_keeps_badge_details(self):
        buf = pb.build(fx.profileScreen())
        self.assertEqual(landmarks(buf), [("Alex's profile", "main")])
        lines = fx.lines(buf)
        self.assertEqual(lines[lines.index("Account Age") + 1], "Sequoia. 7 years, 2 months")

    def test_dm_profile_panel_is_complementary(self):
        self.assertIn(("Alex's profile", "complementary"), landmarks(pb.build(fx.dmScreen())))

    def test_forum_and_thread(self):
        buf = pb.build(fx.forumScreen(withThread=True))
        found = landmarks(buf)
        self.assertIn(("news", "main"), found)
        self.assertIn(("Thread header", "region"), found)
        self.assertIn(("Big release (thread)", "complementary"), found)
        self.assertIn("poster, 11/11/2026 3:47 am", fx.lines(buf))

    def test_discover_menu_and_cards(self):
        buf = pb.build(fx.discoverScreen())
        self.assertIn(("Discover", "navigation"), landmarks(buf))
        self.assertIn("Game Hub, The official server for Game Hub., 5,000 Online, View server", fx.lines(buf))

    def test_quests_cards_are_not_landmarks(self):
        buf = pb.build(fx.questsScreen())
        self.assertEqual([n for n, l in landmarks(buf) if l == "main"], ["Quests"])
        self.assertNotIn("GAME QUEST", [n for n, _ in landmarks(buf)])
        self.assertIn("Avatar Decoration, 15D 4H, View Quest", fx.lines(buf))


class SelfCheckCatchesDiscordChanges(unittest.TestCase):
    """Each test changes the tree the way a Discord update might, and expects a failure."""

    def failed(self, raw, windowClass=pc.WINDOW_CLASS):
        return [c.name for c in pc.runChecks(raw, windowClass) if c.status == pc.FAIL]

    def rename(self, raw, old, new):
        for r in pc._walk(raw):
            if r.name == old:
                r.name = new
                return raw
        self.fail("no element named %r" % old)

    def test_window_class_change(self):
        self.assertIn("Window class is Zed::Window", self.failed(fx.channelScreen(), "Chrome_WidgetWin_1"))

    def test_region_renamed(self):
        names = self.failed(self.rename(fx.channelScreen(), "Servers sidebar", "Server rail"))
        self.assertIn("Region 'Servers sidebar'", names)

    def test_message_list_renamed(self):
        names = self.failed(self.rename(fx.channelScreen(), "Messages in general", "Chat log"))
        self.assertIn("Conversation: message list named 'Messages in ...'", names)

    def test_message_body_no_longer_a_focusable_grouping(self):
        raw = fx.channelScreen()
        for r in pc._walk(raw):
            if pb.isMessageBody(r):
                r.focusable = False
        names = self.failed(raw)
        self.assertIn("Conversation: message body is a focusable grouping 'author , text , time'", names)

    def test_message_headings_gone(self):
        raw = fx.channelScreen()
        for r in pc._walk(raw):
            if pb.isMessageBody(r):
                r.children = [c for c in r.children if not (c.controlType == pb.CT_TEXT and c.headingLevel)]
        self.assertIn("Conversation: message header is a heading inside the body", self.failed(raw))

    def test_page_title_changed_is_unrecognised(self):
        raw = self.rename(fx.questsScreen(), "Quests", "Quest Hub")
        raw.name = "Quest Hub - Discord"
        checks = pc.runChecks(raw, pc.WINDOW_CLASS)
        self.assertEqual(next(c for c in checks if c.name == "Screen recognised").status, pc.WARN)

    def test_settings_sidebar_renamed(self):
        raw = self.rename(fx.settingsScreen(), "Settings sidebar", "Preferences menu")
        self.assertNotEqual(pc.detectScreen(raw).kind, "settings")

    def test_settings_options_no_longer_paired(self):
        raw = fx.settingsScreen()
        for r in pc._walk(raw):
            if r.controlType == pb.CT_BUTTON and r.name == "Enable Desktop Notifications":
                r.name = "Desktop notifications switch"
        lines = fx.lines(pb.build(raw))
        # The label is read again as text: the checker's repeat test can't see
        # it (the names differ), but the reading test does.
        self.assertIn("Enable Desktop Notifications", lines)

    def test_forum_posts_renamed(self):
        raw = fx.forumScreen()
        for r in pc._walk(raw):
            if r.controlType == pb.CT_BUTTON and r.name.startswith("Post "):
                r.name = r.name[len("Post "):]
        self.assertIn("Forum: posts are buttons named 'Post <title>, <n> messages'", self.failed(raw))

    def test_body_name_format_changed(self):
        raw = fx.channelScreen()
        for r in pc._walk(raw):
            if pb.isMessageBody(r):
                r.name = r.name.replace(" , ", " - ")
        # No longer recognised as messages at all.
        self.assertIn("Conversation: message body is a focusable grouping 'author , text , time'", self.failed(raw))


if __name__ == "__main__":
    unittest.main()
