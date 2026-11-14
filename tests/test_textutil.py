from stackbooster.analyzers.textutil import (
    LineIndex,
    find_matching,
    mask_php,
    php_code_only,
    split_top_level,
    strip_c_style_comments,
)


def test_strip_comments_keeps_strings_and_line_numbers():
    src = "a = 'http://x'; // comment\n/* block\n */ b = \"#not\"; # hash\n"
    out = strip_c_style_comments(src, hash_comments=True)
    assert "http://x" in out
    assert "comment" not in out and "block" not in out and "hash" not in out
    assert '"#not"' in out
    assert out.count("\n") == src.count("\n")
    assert len(out) == len(src)


def test_line_comment_stops_at_php_close_tag():
    out = strip_c_style_comments("<?php // note ?><b>x</b>")
    assert "?><b>x</b>" in out


def test_mask_php_and_php_code_only_are_complementary():
    src = "<p><?php echo $x; ?></p>\n<?= $y ?>"
    masked = mask_php(src)
    code = php_code_only(src)
    assert "<p>" in masked and "echo" not in masked
    assert "echo $x" in code and "<p>" not in code
    assert len(masked) == len(code) == len(src)


def test_line_index():
    idx = LineIndex("a\nbb\nccc", first_line=10)
    assert idx.line(0) == 10
    assert idx.line(2) == 11
    assert idx.line(6) == 12


def test_find_matching_ignores_brackets_in_strings():
    text = "f(a, ')', (b))"
    assert find_matching(text, 1) == len(text) - 1


def test_split_top_level():
    assert split_top_level("a int(11), b decimal(10,2), KEY (a, b)") == [
        "a int(11)",
        "b decimal(10,2)",
        "KEY (a, b)",
    ]
