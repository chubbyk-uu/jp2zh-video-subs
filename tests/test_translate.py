from translate_srt_hymt import (
    Entry,
    GlossaryTerm,
    build_messages,
    clean_translation,
    glossary_issues,
    glossary_instruction,
    is_context_sensitive_short_text,
    matched_glossary_terms,
    normalize_source,
    padded_time,
    parse_srt,
    write_terms_report,
)


TEST_GLOSSARY = (
    GlossaryTerm(
        source="中央公園",
        target="中央公园",
        note="地名术语；不要译为车站名。",
        forbidden=("中央公园站",),
    ),
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
    assert is_context_sensitive_short_text("え？") is True
    assert is_context_sensitive_short_text("今日はいい天気ですね") is False


def test_normalize_source_leaves_text_unchanged_without_replacements():
    assert normalize_source("今日はいい天気ですね") == "今日はいい天気ですね"


def test_glossary_instruction_is_in_prompt():
    instruction = glossary_instruction(TEST_GLOSSARY)

    assert "参考下面的翻译" in instruction
    assert "中央公園 翻译成 中央公园" in instruction


def test_matched_glossary_terms_uses_current_source_only():
    terms = (
        GlossaryTerm("ご主人様", "主人", ""),
        GlossaryTerm("主人", "老公", ""),
        GlossaryTerm("中央公園", "中央公园", ""),
    )

    assert [term.source for term in matched_glossary_terms("ご主人様です", terms)] == ["ご主人様"]
    assert matched_glossary_terms("書類にサインをもらいたいのですが。", terms) == ()


def test_build_messages_includes_default_glossary():
    msgs = build_messages("中央公園", [], glossary=TEST_GLOSSARY)

    assert [msg["role"] for msg in msgs] == ["user"]
    assert "中央公園 翻译成 中央公园" in msgs[0]["content"]
    assert msgs[0]["content"].endswith("中央公園")


def test_glossary_issues_reports_forbidden_translation_without_fixing():
    issues = glossary_issues("中央公園", "中央公园站。", TEST_GLOSSARY)

    assert [issue.source for issue in issues] == ["中央公園"]
    assert glossary_issues("中央公園", "中央公园。", TEST_GLOSSARY) == []
    assert glossary_issues("駅に行きます", "去车站。", TEST_GLOSSARY) == []


def test_write_terms_report(tmp_path):
    path = tmp_path / "terms.txt"
    entry = Entry("1", "00:00:01,000 --> 00:00:02,000", "中央公園", 1.0, 2.0)

    write_terms_report(path, [(entry, "中央公园站。", [TEST_GLOSSARY[0]])])

    report = path.read_text(encoding="utf-8")
    assert "Terminology review report" in report
    assert "source: 中央公園" in report
    assert "translation: 中央公园站。" in report


def test_build_messages_without_history_is_single_instructed_turn():
    msgs = build_messages("こんにちは", [])
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert "只需要输出翻译后的结果" in msgs[0]["content"]
    assert msgs[0]["content"].endswith("こんにちは")


def test_build_messages_with_history_uses_chinese_background_only():
    msgs = build_messages("今のセリフ", [("前のセリフ", "上一句译文")])
    assert [m["role"] for m in msgs] == ["user"]
    content = msgs[0]["content"]
    assert "前文译文" in content
    assert "上一句译文" in content
    assert "前のセリフ" not in content
    assert content.endswith("今のセリフ")


def test_build_messages_background_mode_keeps_history_as_reference():
    msgs = build_messages("今のセリフ", [("前のセリフ", "上一句译文")], prompt_mode="background")

    assert [m["role"] for m in msgs] == ["user"]
    content = msgs[0]["content"]
    assert "历史翻译仅用于理解语境" in content
    assert "日文：前のセリフ" in content
    assert "中文：上一句译文" in content
    assert "待翻译日文：\n今のセリフ" in content


def test_build_messages_chat_mode_keeps_legacy_chat_turns():
    msgs = build_messages("今のセリフ", [("前のセリフ", "上一句译文")], prompt_mode="chat")

    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1] == {"role": "user", "content": "前のセリフ"}
    assert msgs[2] == {"role": "assistant", "content": "上一句译文"}
    assert msgs[3] == {"role": "user", "content": "今のセリフ"}


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
