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


def message(author, body, time, fullDate, reply=None, extra=(), tag="ABCD", headed=True):
    """A message row: LISTITEM > [SEPARATOR date] > GROUPING "author , text , time"."""
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
    kids.append(group(body, [text(body)]))
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
            node(pb.CT_TABITEM, "Online", focusable=True, hasSelectionItem=True, selected=True)])]),
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


def lines(buf):
    out = []
    for i, start in enumerate(buf.lineStarts):
        end = buf.lineStarts[i + 1] if i + 1 < len(buf.lineStarts) else len(buf.text)
        out.append(buf.text[start:end].rstrip("\n"))
    return out
