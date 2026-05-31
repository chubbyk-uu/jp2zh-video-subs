from translate_srt_hymt import (
    clean_translation,
    is_context_sensitive_short_text,
    looks_context_leaked,
    normalize_source,
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
