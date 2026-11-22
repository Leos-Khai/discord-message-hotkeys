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
        self.assertIn("Message list named 'Messages in ...'", names)

    def test_message_body_no_longer_a_focusable_grouping(self):
        raw = fx.channelScreen()
        for r in pc._walk(raw):
            if pb.isMessageBody(r):
                r.focusable = False
        names = self.failed(raw)
        self.assertIn("Message body: focusable grouping 'author , text , time'", names)

    def test_message_headings_gone(self):
        raw = fx.channelScreen()
        for r in pc._walk(raw):
            if pb.isMessageBody(r):
                r.children = [c for c in r.children if not (c.controlType == pb.CT_TEXT and c.headingLevel)]
        self.assertIn("Message header: a heading inside the body", self.failed(raw))

    def test_body_name_format_changed(self):
        raw = fx.channelScreen()
        for r in pc._walk(raw):
            if pb.isMessageBody(r):
                r.name = r.name.replace(" , ", " - ")
        # No longer recognised as messages at all.
        self.assertIn("Message body: focusable grouping 'author , text , time'", self.failed(raw))


if __name__ == "__main__":
    unittest.main()
