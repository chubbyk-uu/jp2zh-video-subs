from translate_srt_hymt import (
    Entry,
    build_messages,
    clean_translation,
    is_context_sensitive_short_text,
    normalize_source,
    padded_time,
    parse_srt,
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


def test_normalize_source_leaves_text_unchanged_without_replacements():
    assert normalize_source("今日はいい天気ですね") == "今日はいい天気ですね"


def test_build_messages_without_history_is_single_instructed_turn():
    msgs = build_messages("こんにちは", [])
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert "翻译" in msgs[0]["content"]
    assert msgs[0]["content"].endswith("こんにちは")


def test_build_messages_with_history_keeps_current_turn_source_only():
    # Prior pair becomes user/assistant turns; the current turn carries only the current
    # source, so the model has no previous-line text to fuse into the output.
    msgs = build_messages("今のセリフ", [("前のセリフ", "上一句译文")])
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert "前のセリフ" in msgs[0]["content"] and "翻译" in msgs[0]["content"]
    assert msgs[1] == {"role": "assistant", "content": "上一句译文"}
    assert msgs[2] == {"role": "user", "content": "今のセリフ"}


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
