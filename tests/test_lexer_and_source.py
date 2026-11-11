from readablec import lexer
from readablec.encoding import detect_encoding
from readablec.source import SourceText


def kinds(data: bytes) -> list[tuple[str, bytes]]:
    return [(token.kind, token.text) for token in lexer.tokenize(data)]


def test_directive_spans_continuations_and_keeps_its_line():
    tokens = lexer.tokenize(b"#define TWICE(x) \\\n ((x) * 2)\nint y;\n")
    assert tokens[0].kind == lexer.DIRECTIVE
    assert lexer.normalize_directive(tokens[0].text) == b"#define TWICE(x) ((x) * 2)"
    assert [token.text for token in tokens[1:]] == [b"int", b"y", b";"]


def test_comment_before_hash_still_starts_a_directive():
    tokens = lexer.tokenize(b"/* note */ #if A\n#endif\n")
    assert [token.kind for token in tokens] == [lexer.COMMENT, lexer.DIRECTIVE, lexer.DIRECTIVE]


def test_hash_in_the_middle_of_a_line_is_not_a_directive():
    assert kinds(b"x = y # z;")[3] == (lexer.PUNCTUATOR, b"#")


def test_literals_comments_and_escapes():
    tokens = lexer.tokenize(b's = "a\\"b"; c = \'\\n\'; /* x */ // y\n')
    texts = [(token.kind, token.text) for token in tokens]
    assert (lexer.STRING, b'"a\\"b"') in texts
    assert (lexer.CHAR, b"'\\n'") in texts
    assert [token.kind for token in tokens if token.kind == lexer.COMMENT] == [
        lexer.COMMENT,
        lexer.COMMENT,
    ]


def test_unterminated_block_comment_runs_to_the_end():
    token = lexer.tokenize(b"int x; /* open")[-1]
    assert token.kind == lexer.COMMENT
    assert not token.terminated


def test_line_comment_continues_after_a_backslash():
    tokens = lexer.tokenize(b"// first \\\n second\nint z;\n")
    assert tokens[0].kind == lexer.COMMENT
    assert tokens[1].text == b"int"


def test_contexts_report_depth_comments_and_conditionals():
    data = b"#if A\nvoid f(void) {\n  /* c\n */\n}\n#endif\n"
    tokens = lexer.tokenize(data)
    inside_comment = data.index(b" */")
    after_brace = data.index(b"  /* c")
    contexts = lexer.contexts_at(data, tokens, [after_brace, inside_comment, len(data)])
    assert contexts[0].braces == 1
    assert contexts[0].conditionals == (b"#if A",)
    assert contexts[1].inside == lexer.COMMENT
    assert contexts[2] == lexer.LexicalContext(None, 0, 0, 0, ())


def test_context_after_a_line_continuation():
    data = b"int x = 1 + \\\n2;\n"
    context = lexer.contexts_at(data, lexer.tokenize(data), [data.index(b"2;")])[0]
    assert context.inside == lexer.CONTINUED_LINE


def test_significant_tokens_ignore_comments_and_layout():
    first = lexer.significant(lexer.tokenize(b"int  x = 1; /* one */\n"))
    second = lexer.significant(lexer.tokenize(b"int x=1;\n"))
    assert first == second


def test_macro_definition():
    macro = lexer.macro_definition(
        lexer.tokenize(b"#define MAX(a, b) ((a) > (b) ? (a) : (b))\n")[0]
    )
    assert macro is not None
    assert macro.name == b"MAX"
    assert macro.parameters == (b"a", b"b")
    assert macro.is_function_like


def test_source_lines_and_line_endings():
    source = SourceText(b"a\r\nbb\r\nccc\r\n")
    assert source.line_count == 3
    assert source.line_bytes(2) == b"bb"
    assert source.line_of(source.line_start(3)) == 3
    assert source.line_endings.describe() == "CRLF"
    assert SourceText(b"a\nb\r\n").line_endings.is_mixed


def test_encoding_detection():
    assert detect_encoding(b"int x;").is_ascii
    assert detect_encoding("/* ü */".encode()).is_utf8
    cyrillic = "/* Комментарий о весах и проверке данных */".encode("cp1251")
    info = detect_encoding(cyrillic)
    assert not info.is_utf8
    assert info.name == "cp1251"
