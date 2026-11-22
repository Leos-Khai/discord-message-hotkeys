# -*- coding: utf-8 -*-
"""Phoenix accessibility trees for tests, built from the shapes recorded live.

Every structure here was taken from the Phoenix client on 2026-11-22 (a
server channel with the member list open, a DM, a group DM, the Friends
tabs, Quests). The names are made up; the shapes - roles, nesting, which
elements are focusable or clickable, and Discord's own UI labels - are real.
If Discord changes its tree, record the new shape here and update the
expectations alongside the add-on.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "addon", "appModules"))

import _phoenixBuffer as pb  # noqa: E402

_ids = [0]


def node(controlType, name="", children=(), **kw):
    _ids[0] += 1
    kw.setdefault("runtimeId", (42, _ids[0]))
    return pb.RawNode(controlType, name, children=list(children), **kw)


def text(name="", children=(), **kw):
    return node(pb.CT_TEXT, name, children, **kw)


def button(name, children=(), **kw):
    kw.setdefault("focusable", True)
    kw.setdefault("hasInvoke", True)
    return node(pb.CT_BUTTON, name, children, **kw)


def group(name="", children=(), **kw):
    return node(pb.CT_GROUP, name, children, **kw)


def link(name, children=(), **kw):
    kw.setdefault("focusable", True)
    kw.setdefault("hasInvoke", True)
    return node(pb.CT_HYPERLINK, name, children, **kw)


def message(author, body, time, fullDate, reply=None, extra=(), tag="ABCD", headed=True,
            content=None):
    """A message row: LISTITEM > [SEPARATOR date] > GROUPING "author , text , time".

    content: the parts of the text grouping, for formatted messages."""
    who = "%s Server Tag: %s" % (author, tag) if tag else author
    if reply:
        who += " replying to %s" % reply[0]
    kids = []
    if reply:
        kids += [button("Jump To Reply"), button("@%s" % reply[0], hasInvoke=False),
                 button("Server Tag: WXYZ", hasInvoke=False), button(reply[1], hasInvoke=False)]
    if headed:
        kids.append(text("%s %s" % (who, time), headingLevel=3, children=[
            button(author, [text(author)], hasExpandCollapse=True, hasInvoke=False),
            button("Server Tag: %s" % tag, hasExpandCollapse=True, hasInvoke=False),
            text(time), text(fullDate)]))
    kids.append(group(body, content if content is not None else [text(body)]))
    kids.extend(extra)
    return node(pb.CT_LISTITEM, "%s , %s , %s" % (who, body, time),
                [group("%s , %s , %s" % (who, body, time), kids, focusable=True)])


def sidebars(channelsList):
    return [
        text("Server One"),
        button("Go back"), button("Go forward", focusable=False), button("Inbox", hasInvoke=False,
                                                                         hasExpandCollapse=True),
        group("Servers sidebar", [node(pb.CT_TREE, "", [
            node(pb.CT_TREEITEM, "Direct Messages", [text("Direct Messages")], focusable=True,
                 hasSelectionItem=True),
            group("Servers", [
                node(pb.CT_TREEITEM, "Unread messages, Server One", [text("Unread messages, Server One")],
                     focusable=True, hasSelectionItem=True, selected=True),
                text("Server One"),
            ]),
        ], focusable=True)]),
        channelsList,
        group("User status and settings", [
            button("Manage profile and status", [text("Me"), text("Online")], hasInvoke=False,
                   hasExpandCollapse=True),
            button("Mute", hasToggle=True, toggleState=0, hasInvoke=False),
        ]),
    ]


def window(paneChildren, title="#general | Server One - Discord"):
    return node(pb.CT_WINDOW, title, [
        node(pb.CT_PANE, "Discord", paneChildren, focusable=True),
        group(), group(),
        button("Minimize"), button("Maximize"), button("Close"),
    ])


def channelScreen(members=True):
    """A server text channel with the member list open (names changed).

    Runtime IDs restart on every call, so two calls give the same elements -
    the way a rebuild sees an unchanged Discord.
    """
    _ids[0] = 0
    channels = group("Server One (server)", [
        button("Server One, server actions", hasInvoke=False, hasExpandCollapse=True),
        node(pb.CT_LIST, "Channels", [
            node(pb.CT_LISTITEM, "", [link("general (text channel), Text icon",
                                           [node(pb.CT_IMAGE, "Text icon")])]),
        ], focusable=True),
    ])
    msgs = node(pb.CT_LIST, "Messages in general", [
        node(pb.CT_LISTITEM, "", [node(pb.CT_SEPARATOR, "18 November, 2026", focusable=True)]),
        message("Ann", "hello there", "18/11/2026 7:03 am", "Wednesday, 18 November, 2026 7:03 am",
                extra=[node(pb.CT_BUTTON, "lizard, 1 reaction, press to react", focusable=True,
                            hasToggle=True, toggleState=0)]),
        message("Ann", "second line of thought", "7:04 am", "", headed=False),
        message("Bob", "6 7!", "18/11/2026 8:11 am", "Wednesday, 18 November, 2026 8:11 am",
                reply=("Ann", "hello there")),
        message("Cat", "line one\nline two\nline three", "8:49 am", "Today at 8:49 am",
                extra=[group("", [link("https://example.com/x"), node(pb.CT_IMAGE, "Video"),
                                  button("Play")])]),
    ], focusable=True)
    conversation = group("general (channel)", [
        text("general chat", headingLevel=2),
        node(pb.CT_DOCUMENT, "", [msgs]),
        button("More message options", hasInvoke=False, hasExpandCollapse=True),
        node(pb.CT_EDIT, "Message #general", focusable=True, hasValue=True, value=""),
        button("Send a gift", hasInvoke=False, hasExpandCollapse=True),
        text("Upgrade your friends! Gift them awesome chat perks with Nitro."),
        button("Open GIF picker", hasInvoke=False, hasExpandCollapse=True),
        text("Send GIF"),
    ])
    pane = sidebars(channels) + [
        group("Channel header", [text("Text Channel"), text("general", headingLevel=1),
                                 button("Show Member List")]),
        conversation,
    ]
    if members:
        pane.append(group("Members list for general (channel)", [
            text("Members list for general (channel)", headingLevel=2),
            node(pb.CT_LIST, "Members", [
                text("Admin, 1 member", headingLevel=3, children=[text("Admin"), text("\xa0— 1")]),
                node(pb.CT_LISTITEM, "jo_user, Online Jo Server Tag: ABCD Playing Game", [
                    node(pb.CT_IMAGE, "jo_user, Online"), text("Jo"), text("Server Tag: ABCD"),
                    group("Playing Game", [text("Game"), text("Game")]),
                ], focusable=True, hasInvoke=True),
            ], focusable=True),
        ]))
    pane.append(node(pb.CT_SEPARATOR, "Resize Sidebar", focusable=True))
    return window(pane)


def formattedScreen():
    """A channel with a code block, a quote, headings and lists (recorded 2026-11-22)."""
    screen = channelScreen()
    li = lambda *parts: node(pb.CT_LISTITEM, "", list(parts))
    msgs = _find(screen, lambda n: n.name == "Messages in general")
    msgs.children += [
        message("Ann", "Code block: line one\nline two", "12:07 pm", "Today at 12:07 pm", content=[
            text("Code block:"), text("", [text("line one\nline two")]), button("Copy")]),
        message("Ann", "a quote\n> more quote\nafter", "12:07 pm", "", headed=False, content=[
            group("", [text("a quote\n> more quote\nafter")])]),
        message("Ann", "Smaller heading bullet one 1. first", "12:08 pm", "", headed=False, content=[
            text("Smaller heading", headingLevel=2),
            node(pb.CT_LIST, "", [li(text("bullet one"))]),
            node(pb.CT_LIST, "", [li(text("1."), text("first"))])]),
        # The mouse is over this one: its hover toolbar is in the tree.
        message("Ann", "just text", "12:09 pm", "", headed=False, extra=[group("Message Actions", [
            button("Click to react with thumbsup"), text(":thumbsup:"), button("Edit"), button("More")])]),
    ]
    # A reply in a server channel: the author button has no "@" and opens the profile.
    reply = message("Bob", "a server reply", "12:12 pm", "Today at 12:12 pm")
    body = reply.children[0]
    body.children[:0] = [button("Jump To Reply"),
                         button("Ann", [text("Ann")], hasExpandCollapse=True, hasInvoke=False),
                         button("Server Tag: WXYZ", hasExpandCollapse=True, hasInvoke=False),
                         button("Code block: line one line two", [text(""), text("", [text("line one")])])]
    msgs.children.append(reply)
    msgs.children += [
        # Mentions are buttons in the line; the plain words are an unnamed run.
        message("Cy", "@Ann @Bob swap roles", "12:20 pm", "Today at 12:20 pm", content=[
            button("@Ann", [text("")], hasExpandCollapse=True, hasInvoke=False),
            button("@Bob", [text("")], hasExpandCollapse=True, hasInvoke=False), text("")]),
        # Inline code beside a list: plain runs unnamed, so the summary is read.
        message("Cy", "The 7 with old says: one", "12:21 pm", "", headed=False, content=[
            text("", [text("The 7 with old")]), text(""), text("", [text("says")]), text(":"),
            node(pb.CT_LIST, "", [li(text("", [text("one")]))])]),
        message("Cy", "fixed it (edited)", "12:22 pm", "", headed=False, content=[
            text(""), text("Edited Today at 12:23 pm", [text("(edited)")])]),
        # A thread started from a message: the summary runs on into its button.
        # A hidden spoiler: a button with no Invoke inside the line.
        message("Cy", "Spoiler Spoiler and a link https://example.com/", "12:23 pm", "", headed=False, content=[
            text(""), button("Spoiler", hasInvoke=False, hasExpandCollapse=True), text(""),
            link("https://example.com/")]),
        # Spoilers the summary already names: the whole message, and at the end.
        message("Cy", "Spoiler", "12:25 pm", "", headed=False, content=[
            button("Spoiler", hasInvoke=False, hasExpandCollapse=True)]),
        message("Cy", "this is Spoiler", "12:26 pm", "", headed=False, content=[
            text(""), button("Spoiler", hasInvoke=False, hasExpandCollapse=True)]),
        # Two spoilers in one message (recorded in a thread, 2026-11-22).
        message("Cy", "a Spoiler b Spoiler", "12:27 pm", "", headed=False, content=[
            text(""), button("Spoiler", hasInvoke=False, hasExpandCollapse=True),
            text(""), button("Spoiler", hasInvoke=False, hasExpandCollapse=True)]),
        message("Cy", "start here", "12:24 pm", "", headed=False,
                extra=[button("Thread Plans 1 Message ›", [text("Plans"), text("1 Message ›")])]),
    ]
    started = msgs.children[-1]
    started.name = started.children[0].name = "Cy Server Tag: ABCD , start here Thread Plans 1 Message › , 12:24 pm"
    return screen


def inboxRoleIconScreen():
    """An Inbox mention whose header is TEXT author + BUTTON "Role icon, ..."."""
    screen = channelScreen()
    msgs = _find(screen, lambda n: n.name == "Messages in general")
    m = message("Dee", "ping", "10:09 am", "Today at 10:09 am", tag="")
    m.children[0].children[0].children = [text("Dee"), button("Role icon, Admin", [node(pb.CT_IMAGE, "Role icon, Admin")]),
                                          text("10:09 am")]
    msgs.children.append(m)
    return screen


def _find(raw, test):
    if test(raw):
        return raw
    for ch in raw.children:
        found = _find(ch, test)
        if found is not None:
            return found
    return None


def friendsScreen():
    """The Friends page, Online tab (names changed)."""
    _ids[0] = 0
    dms = group("Private channels", [
        button("Find or start a conversation", [text("Find or start a conversation")]),
        node(pb.CT_LIST, "Direct Messages", [
            node(pb.CT_LISTITEM, "", [link("Friends 1")]),
            node(pb.CT_LISTITEM, "", [link("Alex (direct message), Online", [
                node(pb.CT_IMAGE, "alex_user, Online"), text("Server Tag: ABCD")])]),
        ], focusable=True),
    ])
    friends = group("Friends", [
        group("Friends", [text("Friends", headingLevel=1), node(pb.CT_TAB, "Friends", [
            tab("Online", selected=True), tab("All"), tab("Pending, 1 new"), tab("Suggestions, 2 new"),
            tab("Add Friend")])]),
        node(pb.CT_PANE, "Online — 2", [
            node(pb.CT_EDIT, "Search", focusable=True, hasValue=True, value=""),
            node(pb.CT_LIST, "", [
                node(pb.CT_LISTITEM, "", [
                    button("Open conversation with Sam"), node(pb.CT_IMAGE, "sam1234, Idle"),
                    text("Sam"), text("sam1234"), text("Idle"),
                    button("Message Sam"), button("More options for Sam"),
                ]),
            ]),
        ]),
        group("Active Now", [text("Active Now"), button("Sam Game – 2h", [
            text("Sam"),
            button("View Game Profile", [text("Game – 2h")]),
            button("View Game Profile"), button("View Game Profile"),
        ], hasInvoke=False, hasExpandCollapse=True)]),
    ])
    return window(sidebars(dms) + [friends, node(pb.CT_SEPARATOR, "Resize Sidebar", focusable=True)],
                  title="Friends - Discord")


def tab(name, selected=False):
    return node(pb.CT_TABITEM, name, focusable=True, hasSelectionItem=True, selected=selected)


def dmSidebar():
    return group("Private channels", [
        button("Find or start a conversation", [text("Find or start a conversation")]),
        node(pb.CT_LIST, "Direct Messages", [node(pb.CT_LISTITEM, "", [link("Friends 1")])], focusable=True),
    ])


def serverSidebar(server="Server One", channels=()):
    return group("%s (server)" % server, [
        button("%s, server actions" % server, hasInvoke=False, hasExpandCollapse=True),
        node(pb.CT_LIST, "Channels", [node(pb.CT_LISTITEM, "", [link(c)]) for c in channels] or
             [node(pb.CT_LISTITEM, "", [link("general (text channel)")])], focusable=True),
    ])


def page(title, content, windowTitle=None, channelsList=None):
    """A page with no conversation: the content sits loose in the main pane."""
    _ids[0] = 0
    pane = sidebars(channelsList if channelsList is not None else dmSidebar())
    pane[0] = text(title)
    return window(pane + list(content) + [node(pb.CT_SEPARATOR, "Resize Sidebar", focusable=True)],
                  title=windowTitle or "%s - Discord" % title)


def dmScreen(group_=False):
    """A DM (with the profile panel open), or a group DM."""
    _ids[0] = 0
    name = "Crew" if group_ else "Alex"
    header = group("Channel header", [text("Direct Message"), button(name)]) if not group_ else \
        group("Channel header", [button("Edit Group, %s" % name), button("Start Voice Call")])
    msgs = node(pb.CT_LIST, "Messages in %s" % name, [
        node(pb.CT_LISTITEM, "", [node(pb.CT_SEPARATOR, "21 October, 2026", focusable=True)]),
        message("Alex", "hi there", "21/10/2026 8:59 pm", "Wednesday, 21 October, 2026 8:59 pm"),
        message("Me", "hello", "21/10/2026 9:00 pm", "Wednesday, 21 October, 2026 9:00 pm"),
    ], focusable=True)
    conversation = group("%s (channel)" % name, [
        text("%s chat" % name, headingLevel=2), node(pb.CT_DOCUMENT, "", [msgs]),
        node(pb.CT_EDIT, "Message @%s" % name, focusable=True, hasValue=True, value=""),
    ])
    pane = sidebars(dmSidebar())
    pane[0] = text("Direct Messages")
    pane += [header, conversation]
    if not group_:
        pane.append(group("Alex's profile", [text("Alex's profile", headingLevel=2),
                                            button("View Full Profile", [node(pb.CT_IMAGE, "alex_user, Online")])]))
    return window(pane, title=("%s - Discord" % name) if group_ else "@Alex - Discord")


def forumScreen(withThread=False):
    """A forum channel's post list, optionally with a post open beside it."""
    _ids[0] = 0
    pane = sidebars(serverSidebar(channels=["news (forum channel)"]))
    pane += [
        group("Channel header", [text("Forum Channel"), text("Server One:", headingLevel=1),
                                 text("news", headingLevel=1)]),
        text("Threads", headingLevel=2),
        node(pb.CT_LIST, "news", [
            group("Create Post", [node(pb.CT_EDIT, "Post title", focusable=True), button("New Post")]),
            node(pb.CT_LISTITEM, "", [button("Post Big release, 0 messages, out now", [text("Big release")]),
                                      link("poster, post author")]),
        ], focusable=True),
    ]
    if withThread:
        pane += [
            group("Thread header", [text("Thread:"), text("Big release", headingLevel=2), button("Close")]),
            group("Big release (thread)", [
                text("Big release chat", headingLevel=2),
                node(pb.CT_DOCUMENT, "", [node(pb.CT_LIST, "Messages in Big release", [
                    node(pb.CT_LISTITEM, "", [node(pb.CT_SEPARATOR, "new, 11 November, 2026", focusable=True)]),
                    message("poster", "out now", "11/11/2026 3:47 am", "Wednesday, 11 November, 2026 3:47 am"),
                ], focusable=True)]),
                node(pb.CT_EDIT, "Message Big release", focusable=True, hasValue=True, value=""),
            ]),
        ]
    return window(pane, title="#news | Server One - Discord")


def announcementScreen():
    _ids[0] = 0
    msgs = node(pb.CT_LIST, "Messages in updates", [
        node(pb.CT_LISTITEM, "", [text("This is the start of the #updates channel.")]),
        node(pb.CT_LISTITEM, "", [node(pb.CT_SEPARATOR, "19 September, 2026", focusable=True)]),
        message("Admin", "Version 2 is out", "19/9/2026 9:41 pm", "Saturday, 19 September, 2026 9:41 pm"),
    ], focusable=True)
    pane = sidebars(serverSidebar(channels=["updates (announcement channel)"]))
    pane += [
        group("Channel header", [text("Announcement Channel"), text("updates", headingLevel=1),
                                 button("Follow")]),
        group("updates (channel)", [text("updates chat", headingLevel=2), node(pb.CT_DOCUMENT, "", [msgs]),
                                    text("Follow to get this channel's updates in your own server."),
                                    button("Follow")]),
    ]
    return window(pane, title="#updates | Server One - Discord")


def discoverScreen():
    _ids[0] = 0
    pane = sidebars(dmSidebar())
    pane[0] = text("Discover")
    pane[5] = group("", [text("Discover", headingLevel=1), node(pb.CT_TAB, "", [tab("Apps"), tab("Servers", True)])])
    pane += [
        text("", [text("Find your community on Discord")]),
        text("Featured Servers", headingLevel=2),
        button("View server", [text("Game Hub"), text("The official server for Game Hub."), text("5,000 Online")]),
        node(pb.CT_TAB, "", [tab("Home", True), tab("Gaming")]),
        node(pb.CT_EDIT, "Search", focusable=True),
        node(pb.CT_SEPARATOR, "Resize Sidebar", focusable=True),
    ]
    return window(pane, title="Servers - Discord")


def questsScreen():
    return page("Quests", [
        node(pb.CT_TAB, "", [tab("All Quests", True), tab("Claimed Quests")]),
        button("View Quest", [text("Avatar Decoration"), text("15D 4H")]),
        text("Available Quests", headingLevel=2),
        group("GAME QUEST", [node(pb.CT_IMAGE, "Game quest banner"), text("Promoted by"),
                             text("GAME QUEST", headingLevel=2, children=[text("Game Quest")]),
                             text("700 Orbs"), button("Launch Quest")], focusable=True),
    ])


def shopScreen():
    return page("Shop", [button("Discord Shop"), node(pb.CT_LIST, "", [node(pb.CT_LISTITEM, "", [link("Featured")])]),
                         node(pb.CT_COMBOBOX, "Search the Shop", focusable=True)])


def nitroScreen():
    return page("Nitro", [text("Nitro", headingLevel=2), button("Gift Nitro")], windowTitle="Discord")


def messageRequestsScreen():
    return page("Message Requests", [node(pb.CT_TAB, "", [tab("Requests", True), tab("Spam (3)")]),
                                     text("There are no pending message requests.")])


def _modalWindow(modal, title="@Alex - Discord"):
    _ids[0] = 1000
    return node(pb.CT_WINDOW, title, [
        node(pb.CT_PANE, "Discord", [], focusable=True),
        modal,
        button("Minimize"), button("Maximize"), button("Close"),
    ])


def settingsScreen():
    """User Settings, Notifications page - a modal over an emptied main pane."""
    _ids[0] = 0
    row = lambda label, desc: group("", [text(label), text(desc), node(  # noqa: E731
        pb.CT_BUTTON, label, focusable=True, hasToggle=True, toggleState=1)], focusable=True)
    modal = node(pb.CT_WINDOW, "", [
        group(), group(),
        group("Settings sidebar", [text("Settings sidebar", headingLevel=2), node(pb.CT_LIST, "", [
            node(pb.CT_LISTITEM, "", [text("General", headingLevel=3), node(pb.CT_TAB, "", [
                tab("Account"), tab("Data & Privacy"), tab("Notifications", True), tab("Voice & Video"),
                tab("Appearance"), tab("Accessibility")])])])]),
        text("Notifications", headingLevel=1),
        group("Breadcrumb", [node(pb.CT_LIST, "", [node(pb.CT_LISTITEM, "Notifications")])]),
        button("Close"),
        group("", [node(pb.CT_PANE, "", [group("Overview", [
            text("Overview", headingLevel=2),
            row("Enable Desktop Notifications", "Shows notifications on your desktop."),
            row("Enable Taskbar Flashing", "Flashes the app in your taskbar."),
            group("", [text("Someone reacts to my messages"), text("Someone reacts to my messages"),
                       node(pb.CT_COMBOBOX, "Someone reacts to my messages", focusable=True, hasValue=True,
                            value="All Messages", hasExpandCollapse=True)], focusable=True),
        ], focusable=True)])], focusable=True),
    ], focusable=True)
    return _modalWindow(modal)


def profileScreen():
    """A full user profile - a modal named "<name>'s profile"."""
    _ids[0] = 0
    modal = node(pb.CT_WINDOW, "Alex's profile", [
        text("Alex's profile", headingLevel=1),
        button("View Profile Picture", [node(pb.CT_IMAGE, "alex_user, Online")]),
        text("alex_user"), text("They/Them"),
        group("User Badges", [link("Account Age"), text("Account Age Sequoia. 7 years, 2 months")]),
        button("Message"), button("More", hasInvoke=False, hasExpandCollapse=True),
        group("Member Since", [text("Member Since", headingLevel=2), text("Sep 17, 2019")]),
        node(pb.CT_TAB, "", [tab("Activity", True), tab("3 Mutual Friends")]),
        button("Close"),
    ], focusable=True)
    return _modalWindow(modal)


def profileCardScreen():
    """A member's profile card, opened from the member list - a modal with no tabs."""
    _ids[0] = 0
    modal = node(pb.CT_WINDOW, "Kim's profile", [
        group(), group(),
        text("Kim's profile", headingLevel=1),
        button("View Full Profile", [node(pb.CT_IMAGE, "kim_user, Idle")]),
        button("Kim", [text("Kim")]), text("He/Him"),
        group("Bio", [text("Bio", headingLevel=2), group("Hello there.")]),
        node(pb.CT_LIST, "Roles", [node(pb.CT_LISTITEM, "Mods", [text("Mods"), button("Remove role Mods")],
                                        focusable=True)]),
        node(pb.CT_EDIT, "Message @Kim", focusable=True),
    ], focusable=True)
    return _modalWindow(modal)


def inboxScreen():
    """The Inbox popup, Mentions tab - a modal named "Inbox"."""
    _ids[0] = 0
    mention = node(pb.CT_GROUP, "Kim Server Tag: ABCD , ping @Me , 7:10 am", [
        text("Kim Server Tag: ABCD 7:10 am", headingLevel=3, children=[button("Kim", hasInvoke=False)]),
        group("ping @Me", [text("ping @Me")]),
    ], focusable=True)
    modal = node(pb.CT_WINDOW, "Inbox", [
        group(), group(), text("Inbox"), button("View Friend Requests, 0"),
        node(pb.CT_TAB, "", [tab("Unreads"), tab("Mentions", True), tab("Bookmarks")]),
        node(pb.CT_LISTITEM, "", [button("general, Server One › Text Channels"), button("Jump to Message")]),
        mention,
    ], focusable=True)
    return _modalWindow(modal)


def contextMenuScreen():
    """A message's right-click menu - a menu beside the emptied main pane."""
    _ids[0] = 0
    item = lambda name, **kw: node(pb.CT_MENUITEM, name, focusable=True, hasInvoke=True, **kw)  # noqa: E731
    return node(pb.CT_WINDOW, "#general | Server One - Discord", [
        node(pb.CT_PANE, "Discord", [], focusable=True),
        group(), group(),
        button("Minimize"), button("Maximize"), button("Close"),
        node(pb.CT_MENU, "Message Actions", [
            item("Add Reaction: thumbsup :thumbsup: :+1: :thumbup:"),
            node(pb.CT_SEPARATOR, ""), item("Reply"), item("Copy Text"),
        ], focusable=True),
    ])


def _inCall(userArea):
    """The user area while connected: in-call controls, some nameless with a label text beside them."""
    userArea.children[:0] = [
        button("Voice Details"), link("General / Server One"), button("Disconnect"),
        node(pb.CT_BUTTON, "", focusable=True, hasToggle=True, toggleState=0), text("Turn On Camera"),
        node(pb.CT_BUTTON, "", focusable=True, hasToggle=True, toggleState=0), text("Share Your Screen"),
        text("Start An Activity"), button(""),
    ]
    return userArea


def voiceScreen(withChat=False):
    """A voice channel's call view, optionally with its text chat open."""
    _ids[0] = 0
    pane = sidebars(serverSidebar(channels=["general (text channel)"]))
    _inCall(pane[6])
    pane += [
        text("Voice Channel General", headingLevel=1, children=[text("General")]),
        button("Show Chat"), button("Mute"), button("Turn On Camera"), button("Disconnect"),
        node(pb.CT_IMAGE, "Me"), button("Call tile, me_user"), button("Invite to Voice"),
    ]
    if withChat:
        pane += [
            group("Thread header", [text("General"), button("Close")]),
            group("Text chat for voice channel General", [
                text("General chat", headingLevel=2),
                node(pb.CT_DOCUMENT, "", [node(pb.CT_LIST, "Messages in General", [
                    node(pb.CT_LISTITEM, "", [text("This is the start of the General channel.")]),
                ], focusable=True)]),
                node(pb.CT_EDIT, "Message General", focusable=True),
            ]),
        ]
    return window(pane, title="#general | Server One - Discord")


def stageScreen(withChat=False):
    """A stage channel waiting to start, optionally with its text chat open."""
    _ids[0] = 0
    pane = sidebars(serverSidebar(channels=["general (text channel)"]))
    pane += [
        text("Waiting for the Stage to start", headingLevel=1),
        button("Start the Stage", [text("Pick a topic to start the conversation.")]),
        button("Request to Speak"), button("Disconnect Quietly"),
        button("Stage Channel", focusable=False), text("stage-one"),
        text("0 is speaking"), text("1 in audience"),
    ]
    if withChat:
        pane.append(group("Text chat for stage channel stage-one", [
            text("stage-one chat", headingLevel=2),
            node(pb.CT_DOCUMENT, "", [node(pb.CT_LIST, "Messages in stage-one", [
                node(pb.CT_LISTITEM, "", [text("This is the start of the stage-one channel.")]),
            ], focusable=True)]),
            node(pb.CT_EDIT, "Message stage-one", focusable=True),
        ]))
    else:
        pane.append(button("Show Chat"))
    return window(pane, title="stage-one | Server One - Discord")


def _settingsModal(name, sections, content):
    """Server or Channel Settings: an unnamed grouping of tab lists, then the page."""
    return node(pb.CT_WINDOW, name, [
        group(), group(),
        group("", [node(pb.CT_TAB, title, [tab(p) for p in pages]) for title, pages in sections]),
    ] + content + [button("Close, ESC")], focusable=True)


def serverSettingsScreen():
    _ids[0] = 0
    return _modalWindow(_settingsModal("", [
        ("Server One", ["Server Profile", "Server Tag", "Engagement"]),
        ("People", ["Members", "Manage Roles", "Invites"]),
        ("Moderation", ["Safety Setup", "Audit Log", "Bans"]),
    ], [
        text("Server Profile", headingLevel=2),
        text("Name"), node(pb.CT_EDIT, "Name", focusable=True, hasValue=True, value="Server One"),
        node(pb.CT_BUTTON, "Private Profile", focusable=True, hasToggle=True, toggleState=0),
    ]), title="#general | Server One - Discord")


def channelSettingsScreen():
    _ids[0] = 0
    return _modalWindow(_settingsModal("Channel Settings", [
        ("Settings", ["Overview", "Permissions", "Invites", "Integrations"]),
    ], [
        node(pb.CT_PANE, "", [
            text("Overview", headingLevel=2),
            node(pb.CT_EDIT, "Channel Name", focusable=True, hasValue=True, value="general"),
            node(pb.CT_COMBOBOX, "Slowmode", focusable=True, hasValue=True, value="Off"),
        ]),
    ]), title="#general | Server One - Discord")


def pinnedPopupScreen():
    """Pinned Messages: a popup that leaves the channel showing behind it."""
    raw = channelScreen(members=False)
    raw.children.insert(2, node(pb.CT_WINDOW, "Pinned Messages", [
        text("Pinned Messages"),
        node(pb.CT_LIST, "", [text("This channel doesn't have any pinned messages... yet.")]),
    ], focusable=True))
    return raw


def eventsScreen():
    _ids[0] = 0
    return _modalWindow(node(pb.CT_WINDOW, "Events", [
        text("Events"), button("Create Event"), button("Close"), text("There are no upcoming events."),
    ], focusable=True))


def serverMembersScreen():
    content = [text("Members"), text("Recent Members", headingLevel=2), node(pb.CT_EDIT, "Search", focusable=True),
               node(pb.CT_TABLE, "Recent Members", [node(pb.CT_DATAITEM, "", [node(pb.CT_DATAITEM, "Name")])])]
    raw = page("SO", content, windowTitle="Members | Server One - Discord", channelsList=serverSidebar())
    return raw


def browseChannelsScreen():
    content = [text("Browse Channels"), text("Text Channels"),
               button("general", [text("general"), text("Active 2 years ago")])]
    return page("SO", content, windowTitle="Browse Channels - Server One - Discord", channelsList=serverSidebar())


def serverBoostsScreen():
    content = [text("Server Boosts", headingLevel=1), text("Levels", headingLevel=2), button("Boost This Server")]
    return page("SO", content, windowTitle="Discord", channelsList=serverSidebar())


def lines(buf):
    out = []
    for i, start in enumerate(buf.lineStarts):
        end = buf.lineStarts[i + 1] if i + 1 < len(buf.lineStarts) else len(buf.text)
        out.append(buf.text[start:end].rstrip("\n"))
    return out
