"""verify points at old comments that still name a renamed local, and only at those."""

from conftest import analyse
from readablec.verify import names

BEFORE = (
    "/* Emits the name. cb->server says which side sent it. */\n"
    "static void emit(const struct slot *cb, const char *u)\n{\n"
    "    /* a short name is ignored */\n"
    "    if (u[0]) send(cb->server, u);\n}\n"
)


def stale(before: str, after: str) -> list[str]:
    old, new = analyse(before), analyse(after)
    issues = names.stale_comment_issues(old, [(0, len(old.data))], new, [(0, len(new.data))])
    return [issue.message for issue in issues]


def test_an_old_comment_that_names_a_renamed_parameter_is_reported():
    after = BEFORE.replace("*cb,", "*slot,").replace("send(cb->server", "send(slot->server")
    after = after.replace("const char *u)", "const char *name)").replace(
        "u[0]) send(slot->server, u)", "name[0]) send(slot->server, name)"
    )
    [message] = stale(BEFORE, after)
    assert "still mentions `cb`, which `emit` no longer declares" in message


def test_an_updated_comment_is_not_reported():
    after = BEFORE.replace("*cb,", "*slot,").replace("send(cb->server", "send(slot->server")
    after = after.replace("cb->server says", "slot->server says")
    assert stale(BEFORE, after) == []


def test_new_comments_and_ordinary_words_are_not_reported():
    before = "static int parse(const unsigned char *data)\n{\n    int msgType = data[0];\n    /* a type of 0 is invalid */\n    return msgType;\n}\n"
    after = (
        "static int parse(const unsigned char *data)\n{\n"
        "    /* CLIPRDR_HEADER: msgType(2) + msgFlags(2) + dataLen(4) */\n"
        "    int msg_type = data[0];\n    /* a type of 0 is invalid */\n    return msg_type;\n}\n"
    )
    assert stale(before, after) == []
