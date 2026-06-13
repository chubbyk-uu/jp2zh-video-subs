from translate_srt_galtransl import (
    GALTRANSL_SYSTEM,
    build_messages,
    build_user_prompt,
    glossary_block,
    looks_degenerate,
    relevant_terms,
    translate_block,
    union_terms,
)
from translate_srt_hymt import GlossaryTerm


TEST_GLOSSARY = (
    GlossaryTerm(source="ご主人様", target="主人", note="主仆/角色尊称", forbidden=("老公",)),
    GlossaryTerm(source="主人", target="老公", note="妻子称自己丈夫", forbidden=("主人",)),
)


class _StubLlm:
    """Returns a fixed completion so translate_block's validation can be tested offline."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.last_messages = None

    def create_chat_completion(self, *, messages, **_):
        self.last_messages = messages
        return {"choices": [{"message": {"content": self._content}}]}


def test_translate_block_accepts_matching_line_count():
    assert translate_block(_StubLlm("甲\n乙\n丙"), ["a", "b", "c"], [], ()) == ["甲", "乙", "丙"]


def test_translate_block_drops_blank_lines_before_counting():
    # A stray blank line must not be mistaken for a real cue.
    assert translate_block(_StubLlm("甲\n\n乙\n丙"), ["a", "b", "c"], [], ()) == ["甲", "乙", "丙"]


def test_translate_block_rejects_line_count_mismatch():
    assert translate_block(_StubLlm("甲\n乙"), ["a", "b", "c"], [], ()) is None
    assert translate_block(_StubLlm("甲\n乙\n丙\n丁"), ["a", "b", "c"], [], ()) is None


def test_translate_block_rejects_kana_leak():
    assert translate_block(_StubLlm("甲\nです\n丙"), ["a", "b", "c"], [], ()) is None


def test_translate_block_feeds_one_newline_joined_turn():
    llm = _StubLlm("甲\n乙")
    translate_block(llm, ["x", "y"], [], ())
    user = llm.last_messages[-1]["content"]
    assert "x\ny" in user  # both sources in a single user turn


def test_union_terms_dedupes_across_lines():
    terms = union_terms(["ご主人様だ", "また主人と", "ご主人様ね"], TEST_GLOSSARY)
    sources = [t.source for t in terms]
    assert sources.count("ご主人様") == 1


def test_system_prompt_is_the_official_v3_text():
    # Must match the model card verbatim, including the 换行 clause at the end.
    assert GALTRANSL_SYSTEM.startswith("你是一个视觉小说翻译模型")
    assert "不要混淆使役态和被动态" in GALTRANSL_SYSTEM
    assert GALTRANSL_SYSTEM.endswith("也不要擅自增加或减少换行。")


def test_messages_are_a_single_user_turn():
    msgs = build_messages("こんにちは", [], glossary=())
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == GALTRANSL_SYSTEM


def test_user_prompt_without_history_omits_history_block():
    prompt = build_user_prompt("こんにちは", [], glossary=())
    assert "历史翻译：" not in prompt
    # Glossary header is kept even when empty (model card: 可为空).
    assert prompt.startswith("参考以下术语表（可为空，格式为src->dst #备注）：")
    assert "根据以上术语表的对应关系和备注，结合历史剧情和上下文，将下面的文本从日文翻译成简体中文：" in prompt
    assert prompt.endswith("こんにちは")


def test_user_prompt_with_history_lists_prior_translations_only():
    prompt = build_user_prompt("次のセリフ", ["第一句译文", "第二句译文"], glossary=())
    lines = prompt.splitlines()
    assert lines[0] == "历史翻译：第一句译文"
    assert lines[1] == "第二句译文"
    # A blank line separates history from the glossary header.
    assert lines[2] == ""
    assert lines[3] == "参考以下术语表（可为空，格式为src->dst #备注）："


def test_glossary_block_uses_native_arrow_note_format():
    block = glossary_block("ご主人様、おはよう", TEST_GLOSSARY)
    # Longest-match dedup keeps only ご主人様->主人, not the competing bare 主人->老公.
    assert block == "ご主人様->主人 #主仆/角色尊称"


def test_glossary_block_bare_term_renders_its_own_rule():
    assert glossary_block("主人、ご飯", TEST_GLOSSARY) == "主人->老公 #妻子称自己丈夫"


def test_relevant_terms_skips_unmatched():
    assert relevant_terms("おはよう", TEST_GLOSSARY) == []


def test_full_prompt_shape_matches_official_example():
    prompt = build_user_prompt("ご主人様、おはよう", ["早上好。"], TEST_GLOSSARY)
    expected = (
        "历史翻译：早上好。\n"
        "\n"
        "参考以下术语表（可为空，格式为src->dst #备注）：\n"
        "ご主人様->主人 #主仆/角色尊称\n"
        "\n"
        "根据以上术语表的对应关系和备注，结合历史剧情和上下文，将下面的文本从日文翻译成简体中文：\n"
        "ご主人様、おはよう"
    )
    assert prompt == expected


def test_looks_degenerate_flags_runaway_and_loops():
    assert looks_degenerate("はい", "好" * 30) is True
    assert looks_degenerate("はい", "好的好的好的好的好的好的") is True
    assert looks_degenerate("こんにちは", "你好") is False
    assert looks_degenerate("はい", "") is False
