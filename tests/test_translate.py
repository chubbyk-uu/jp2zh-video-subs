from translate_srt_hymt import (
    Entry,
    clean_translation,
    is_context_bleed,
    is_context_sensitive_short_text,
    looks_context_leaked,
    normalize_source,
    padded_time,
    parse_srt,
    text_ratio,
)


def test_clean_translation_strips_tags_and_labels():
    assert clean_translation("<target>你好</target>") == "你好"
    assert clean_translation("译文：你好") == "你好"
    assert clean_translation("翻译结果: 你好") == "你好"
    assert clean_translation("```\n你好\n```") == "你好"


def test_clean_translation_keeps_first_line_only():
    assert clean_translation("你好\n世界") == "你好"


def test_is_context_sensitive_short_text():
    assert is_context_sensitive_short_text("はい") is True
    assert is_context_sensitive_short_text("……") is True
    assert is_context_sensitive_short_text("今日はいい天気ですね") is False


def test_looks_context_leaked_detects_kana():
    assert looks_context_leaked("はい", "はい、そうですね") is True
    assert looks_context_leaked("はい", "好的") is False


def test_normalize_source_leaves_text_unchanged_without_replacements():
    assert normalize_source("今日はいい天気ですね") == "今日はいい天気ですね"


def test_text_ratio_ignores_whitespace_and_handles_empty():
    assert text_ratio("a b c", "abc") == 1.0
    assert text_ratio("你好世界", "你好世界") == 1.0
    assert text_ratio("", "你好") == 0.0
    assert text_ratio("今天天气怎么样", "你叫什么名字") < 0.5


def test_is_context_bleed_fires_when_translation_echoes_but_source_differs():
    # Different source line, but the translation copies the previous translation.
    assert is_context_bleed(
        source="今天天气怎么样",
        translated="我叫小明",
        previous_source="你叫什么名字",
        previous_translation="我叫小明",
    ) is True


def test_is_context_bleed_ignores_genuinely_repeated_line():
    # Both source and translation stay similar -> a real repeat, not a leak.
    assert is_context_bleed(
        source="没有办公室啊",
        translated="根本没有办公室啊",
        previous_source="没有办公室",
        previous_translation="根本没有办公室",
    ) is False


def test_is_context_bleed_ignores_distinct_translation():
    # Source differs and the translation also differs -> normal, leave it.
    assert is_context_bleed(
        source="我想喝水",
        translated="我想喝水",
        previous_source="天气很好",
        previous_translation="天气很好",
    ) is False


def test_is_context_bleed_needs_a_previous_translation():
    assert is_context_bleed("甲", "乙", "", "") is False


def test_padded_time_keeps_default_timing():
    entry = Entry("1", "00:00:01,000 --> 00:00:02,000", "こんにちは", 1.0, 2.0)
    assert padded_time(entry, None, lead_out=0.0, min_display=0.0) == "00:00:01,000 --> 00:00:02,000"


def test_padded_time_clamps_to_next_entry():
    entry = Entry("1", "00:00:01,000 --> 00:00:02,000", "こんにちは", 1.0, 2.0)
    next_entry = Entry("2", "00:00:02,300 --> 00:00:03,000", "またね", 2.3, 3.0)
    assert padded_time(entry, next_entry, lead_out=1.0, min_display=0.0) == "00:00:01,000 --> 00:00:02,260"


def test_parse_srt_preserves_timing_settings(tmp_path):
    path = tmp_path / "input.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:02,000 position:50%\nこんにちは\n\n",
        encoding="utf-8",
    )
    entry = parse_srt(path)[0]
    assert padded_time(entry, None, lead_out=0.5, min_display=0.0) == (
        "00:00:01,000 --> 00:00:02,500 position:50%"
    )
