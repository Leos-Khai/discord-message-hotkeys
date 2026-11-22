# -*- coding: utf-8 -*-
"""The NVDA side of Phoenix browse mode, against small stand-ins for NVDA.

NVDA can't be imported off-device, so the handful of NVDA modules
_phoenixBrowseMode.py uses are replaced by minimal fakes that behave like the
real ones where this code depends on them. That covers the add-on's own logic
- control fields, quick navigation, the caret across rebuilds, finding objects,
activation - not NVDA's speech, which needs the real thing.
"""
import enum
import importlib
import os
import sys
import types
import unittest

APPMODULES = os.path.join(os.path.dirname(__file__), os.pardir, "addon", "appModules")


def _install_fake_nvda():
    if "appModules._phoenixBrowseMode" in sys.modules:
        return sys.modules["appModules._phoenixBrowseMode"]

    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    Role = enum.IntEnum("Role", (
        "BUTTON TOGGLEBUTTON LINK TREEVIEWITEM TAB MENUITEM CHECKBOX RADIOBUTTON COMBOBOX EDITABLETEXT "
        "SLIDER SPINBUTTON PROGRESSBAR SPLITBUTTON HEADERITEM DATAITEM SCROLLBAR THUMB CALENDAR STATICTEXT "
        "HEADING GRAPHIC SEPARATOR TOOLTIP LISTITEM LIST TREEVIEW TABCONTROL POPUPMENU MENUBAR GROUPING "
        "PANE WINDOW STATUSBAR TOOLBAR HEADER TABLE DATAGRID DOCUMENT TITLEBAR UNKNOWN LANDMARK REGION"))
    State = enum.IntEnum("State", "FOCUSABLE UNAVAILABLE CHECKED HALFCHECKED CHECKABLE PRESSED SELECTED "
                                  "COLLAPSED EXPANDED EDITABLE READONLY LINKED")
    OutputReason = enum.Enum("OutputReason", "FOCUS CARET QUICKNAV")
    mod("controlTypes", Role=Role, State=State, OutputReason=OutputReason)
    mod("wx", CallLater=lambda ms, f, *a: None)
    mod("api", getFocusObject=lambda: None)
    mod("braille", handler=types.SimpleNamespace(handleUpdate=lambda ti: None))
    mod("config", conf={"discordMessageHotkeys": {"phoenixBrowseMode": True}})
    mod("queueHandler", eventQueue=None, queueFunction=lambda q, f, *a: None)
    mod("ui", message=lambda *a: None)
    mod("winUser", isWindow=lambda h: True)
    quiet = lambda *a, **k: None  # noqa: E731
    mod("logHandler", log=types.SimpleNamespace(debugWarning=quiet, error=quiet, debug=quiet))
    mod("scriptHandler", script=lambda **k: (lambda f: f))
    mod("aria", landmarkRoles={k: k for k in ("banner", "complementary", "contentinfo", "main",
                                              "navigation", "search", "form")})

    class FieldCommand(object):
        def __init__(self, command, field):
            self.command, self.field = command, field

    class TextInfo(object):
        def __init__(self, obj, position):
            self.obj, self.basePosition = obj, position

    ti = mod("textInfos", FieldCommand=FieldCommand, ControlField=type("ControlField", (dict,), {}),
             FormatField=type("FormatField", (dict,), {}), POSITION_ALL="all", POSITION_CARET="caret",
             POSITION_SELECTION="selection", POSITION_FIRST="first", UNIT_CONTROLFIELD="controlField",
             UNIT_FORMATFIELD="formatField", UNIT_LINE="line", TextInfo=TextInfo)

    class NVDAObject(object):
        pass

    class Offsets(object):
        def __init__(self, s, e):
            self.startOffset, self.endOffset = s, e

    class OffsetsTextInfo(TextInfo):
        """Like NVDA's: positions by offset, caret and selection via the subclass."""

        def __init__(self, obj, position):
            super(OffsetsTextInfo, self).__init__(obj, position)
            if isinstance(position, NVDAObject):
                position = Offsets(*self._getOffsetsFromNVDAObject(position))
            if type(position) is type(self):
                self.__dict__.update({k: v for k, v in position.__dict__.items() if k.startswith("_")})
            elif position == "all":
                self._startOffset, self._endOffset = 0, self._getStoryLength()
            elif position == "caret":
                self._startOffset = self._endOffset = self._getCaretOffset()
            elif position == "selection":
                self._startOffset, self._endOffset = self._getSelectionOffsets()
            else:
                n = self._getStoryLength()
                self._startOffset = max(min(position.startOffset, n), 0)
                self._endOffset = max(min(position.endOffset, n), 0)

        def _getUnitOffsets(self, unit, offset):
            raise NotImplementedError(unit)

        @property
        def text(self):
            return self._getTextRange(self._startOffset, self._endOffset)

        def copy(self):
            return self.__class__(self.obj, self)

        def updateSelection(self):
            self._setSelectionOffsets(self._startOffset, self._endOffset)

    offsets = types.ModuleType("textInfos.offsets")
    offsets.OffsetsTextInfo, offsets.Offsets = OffsetsTextInfo, Offsets
    sys.modules["textInfos.offsets"] = ti.offsets = offsets

    class TextInfoQuickNavItem(object):
        def __init__(self, itemType, document, textInfo):
            self.itemType, self.document, self.textInfo = itemType, document, textInfo

        def isChild(self, parent):
            return False

    class BrowseModeDocumentTreeInterceptor(object):
        def __init__(self, root):
            self.rootNVDAObject, self._passThrough, self.activated = root, False, None

        def makeTextInfo(self, position):
            return self.TextInfo(self, position)

        def terminate(self):
            pass

        def _set_passThrough(self, state):
            self._passThrough = state

        def _set_selection(self, info, reason=None):
            info.updateSelection()

        def event_gainFocus(self, obj, nextHandler):
            pass

        def _activatePosition(self, obj=None, info=None):
            self.activated = obj

        def _activateNVDAObject(self, obj):
            self.activated = obj

        passThrough = property(lambda s: s._passThrough, lambda s, v: s._set_passThrough(v))

    mod("browseMode", BrowseModeDocumentTextInfo=type("BrowseModeDocumentTextInfo", (TextInfo,), {}),
        TextInfoQuickNavItem=TextInfoQuickNavItem,
        BrowseModeDocumentTreeInterceptor=BrowseModeDocumentTreeInterceptor)

    class UIA(NVDAObject):
        def __init__(self, windowHandle=None, UIAElement=None):
            self.windowHandle, self.UIAElement = windowHandle, UIAElement

    mod("NVDAObjects", NVDAObject=NVDAObject)
    mod("NVDAObjects.UIA", UIA=UIA)
    mod("UIAHandler", handler=None)
    pkg = mod("appModules")
    pkg.__path__ = [APPMODULES]
    return importlib.import_module("appModules._phoenixBrowseMode")


pbm = _install_fake_nvda()
import phoenix_fixtures as fx  # noqa: E402
pb = sys.modules["appModules._phoenixBuffer"]


class _Element(object):
    def __init__(self, rid):
        self.rid = rid

    def GetRuntimeId(self):
        return list(self.rid)


class _Obj(pbm.NVDAObject):
    """An NVDAObject stand-in found by runtime ID, with an optional parent."""

    def __init__(self, rid, parent=None):
        self.UIAElement, self.parent = _Element(rid), parent

    def __eq__(self, other):
        return isinstance(other, _Obj) and other.UIAElement.rid == self.UIAElement.rid

    __hash__ = object.__hash__


def _withElements(raw):
    for r in pc_walk(raw):
        r.element = _Element(r.runtimeId)
    return raw


def pc_walk(raw):
    stack = [raw]
    while stack:
        r = stack.pop()
        yield r
        stack.extend(r.children)


def _document(raw=None):
    doc = pbm.PhoenixBrowseDocument(pbm.UIA(windowHandle=1, UIAElement=_Element((42, 0))))
    doc._swapBuffer(pb.build(_withElements(raw or fx.channelScreen())))
    return doc


def _at(doc, text):
    offset = doc._buffer.text.index(text)
    return doc.makeTextInfo(pbm.textInfos.offsets.Offsets(offset, offset))


class Fields(unittest.TestCase):

    def test_fields_are_balanced_and_nested(self):
        doc = _document()
        depth = 0
        for cmd in doc.makeTextInfo("all").getTextWithFields():
            if isinstance(cmd, str):
                continue
            if cmd.command == "controlStart":
                depth += 1
            elif cmd.command == "controlEnd":
                depth -= 1
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)

    def test_a_line_opens_the_fields_around_it(self):
        doc = _document()
        start, end = doc._buffer.lineOffsets(doc._buffer.text.index("hello there"))
        cmds = doc.makeTextInfo(pbm.textInfos.offsets.Offsets(start, end)).getTextWithFields()
        roles = [c.field["role"] for c in cmds if not isinstance(c, str) and c.command == "controlStart"]
        Role = pbm.controlTypes.Role
        # Phoenix wraps the message list in a document element.
        self.assertEqual(roles[:4], [Role.LANDMARK, Role.DOCUMENT, Role.LIST, Role.LISTITEM])

    def test_only_landmark_types_nvda_knows_are_sent(self):
        # "region" is not one: sending it crashed NVDA's speech with KeyError: 'region'.
        doc = _document()
        for node in doc._buffer.nodes:
            field = doc._controlField(node)
            if "landmark" in field:
                self.assertIn(field["landmark"], pbm.LANDMARK_NAMES)
        user = next(n for n in doc._buffer.nodes if n.fieldName == "User status and settings")
        self.assertEqual(doc._controlField(user)["role"], pbm.controlTypes.Role.REGION)

    def test_tooltip_becomes_field_description(self):
        doc = _document()
        gift = doc._buffer.nodeAt(doc._buffer.text.index("Send a gift"))
        self.assertTrue(doc._controlField(gift)["description"].startswith("Upgrade your friends"))


class QuickNavigation(unittest.TestCase):

    def labels(self, items):
        return [i.textInfo.text.strip() for i in items]

    def test_headings_move_message_by_message(self):
        doc = _document()
        found = self.labels(doc._iterNodesByType("heading3"))
        self.assertEqual(found[:4], ["Ann, 18/11/2026 7:03 am", "Ann, 7:04 am",
                                     "Bob, 18/11/2026 8:11 am", "Cat, 8:49 am"])

    def test_previous_heading(self):
        doc = _document()
        found = self.labels(doc._iterNodesByType("heading3", "previous", _at(doc, "Bob, 18")))
        self.assertEqual(found[0], "Ann, 7:04 am")

    def test_landmarks(self):
        doc = _document()
        names = [i.node.fieldName for i in doc._iterNodesByType("landmark")]
        self.assertEqual(names[0], "Top bar")
        self.assertIn("general (channel)", names)

    def test_unsupported_type_says_so(self):
        with self.assertRaises(NotImplementedError):
            _document()._iterNodesByType("table")


class Caret(unittest.TestCase):

    def test_caret_stays_on_its_message_when_older_ones_load(self):
        doc = _document()
        _at(doc, "Bob, 18").updateSelection()
        raw = fx.channelScreen()
        msgs = next(r for r in pc_walk(raw) if r.name == "Messages in general")
        # The same elements (so the same runtime IDs), plus one older message above.
        msgs.children.insert(1, fx.message("Old", "earlier", "1:00 am", "", headed=True))
        doc._swapBuffer(pb.build(_withElements(raw)))
        caret = doc.makeTextInfo("caret")
        self.assertTrue(doc._buffer.text[caret._startOffset:].startswith("Bob,"))
        self.assertIn("Old, 1:00 am", doc._buffer.text)

    def test_stale_range_still_reads_its_own_text(self):
        doc = _document()
        start, end = doc._buffer.lineOffsets(doc._buffer.text.index("6 7!"))
        stale = doc.makeTextInfo(pbm.textInfos.offsets.Offsets(start, end))
        doc._swapBuffer(pb.build(_withElements(fx.channelScreen())))
        self.assertEqual(stale.text.strip(), "6 7!")


class Objects(unittest.TestCase):

    def test_object_to_position(self):
        doc = _document()
        edit = next(n for n in doc._buffer.nodes if n.role == "edit")
        self.assertEqual(doc.makeTextInfo(_Obj(edit.runtimeId)).text, " \n")

    def test_unrendered_child_maps_to_its_ancestor(self):
        doc = _document()
        edit = next(n for n in doc._buffer.nodes if n.role == "edit")
        info = doc.makeTextInfo(_Obj((7, 7), parent=_Obj(edit.runtimeId)))
        self.assertEqual((info._startOffset, info._endOffset), (edit.start, edit.end))

    def test_unknown_object_raises_lookup_error(self):
        doc = _document()
        doc._lastLoadTime = 10 ** 12  # don't try to refresh
        with self.assertRaises(LookupError):
            doc.makeTextInfo(_Obj((8, 8)))


class Activation(unittest.TestCase):

    def test_enter_on_the_reply_line_presses_jump_to_reply(self):
        doc = _document()
        doc._activatePosition(info=_at(doc, "Replying to @Ann"))
        jump = next(n for n in doc._buffer.nodes if n.raw.name == "Jump To Reply")
        self.assertEqual(doc.activated.UIAElement.rid, jump.runtimeId)

    def test_enter_on_a_follow_on_heading_uses_the_message(self):
        doc = _document()
        doc._activatePosition(info=_at(doc, "Ann, 7:04 am"))
        self.assertIsNotNone(doc.activated)

    def test_enter_on_a_server_selects_it(self):
        doc = _document()
        doc._activatePosition(info=_at(doc, "Unread messages, Server One"))
        item = next(n for n in doc._buffer.nodes if n.role == "treeItem" and n.label.startswith("Unread"))
        self.assertEqual(doc.activated.UIAElement.rid, item.runtimeId)


if __name__ == "__main__":
    unittest.main()
