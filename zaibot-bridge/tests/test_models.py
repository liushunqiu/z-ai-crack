from __future__ import annotations

from bridge.models import Message, InternalRequest, extract_pass_through


class TestMessage:
    def test_creation(self):
        m = Message(role="user", content="hello")
        assert m.role == "user"
        assert m.content == "hello"
        assert m.name is None

    def test_frozen(self):
        m = Message(role="user", content="hello")
        # dataclass(frozen=True) should prevent mutation
        with pytest.raises(Exception):
            m.content = "world"


class TestInternalRequest:
    def test_creation_defaults(self):
        req = InternalRequest(model="GLM-5.1", messages=[Message("user", "hi")])
        assert req.model == "GLM-5.1"
        assert req.stream is True
        assert req.tools is None
        assert req.conversation_id is None

    def test_with_model(self):
        req = InternalRequest(model="GLM-5.1", messages=[])
        req2 = req.with_model("GLM-5")
        assert req2.model == "GLM-5"
        assert req.model == "GLM-5.1"  # original unchanged

    def test_with_messages(self):
        req = InternalRequest(model="GLM-5.1", messages=[])
        msgs = [Message("user", "hello")]
        req2 = req.with_messages(msgs)
        assert req2.messages == msgs
        assert req.messages == []  # original unchanged

    def test_with_conversation_id(self):
        req = InternalRequest(model="GLM-5.1", messages=[])
        req2 = req.with_conversation_id("sid-123")
        assert req2.conversation_id == "sid-123"


class TestExtractPassThrough:
    def test_extracts_known_keys(self):
        body = {"temperature": 0.7, "top_p": 0.9, "unknown": "value"}
        out = extract_pass_through(body)
        assert out == {"temperature": 0.7, "top_p": 0.9}

    def test_ignores_none(self):
        body = {"temperature": None, "top_p": 0.9}
        out = extract_pass_through(body)
        assert out == {"top_p": 0.9}

    def test_empty_body(self):
        assert extract_pass_through({}) == {}


import pytest
