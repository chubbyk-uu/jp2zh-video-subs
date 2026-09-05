from translate_srt_sugoi import (
    numbered_prompt,
    parse_numbered_output,
    safe_translation,
    translate_batch_adaptive,
    translate_one,
)


def test_numbered_prompt_has_stable_identifiers():
    prompt = numbered_prompt(["一行目", "二行目"])
    assert "[001] 一行目" in prompt
    assert "[002] 二行目" in prompt


def test_parse_numbered_output_requires_exact_unique_ids():
    assert parse_numbered_output("[001] First\n[002] Second", 2) == ["First", "Second"]
    assert parse_numbered_output("[001] First", 2) is None
    assert parse_numbered_output("[001] First\n[001] Again", 2) is None
    assert parse_numbered_output("Explanation\n[001] First", 1) is None


def test_safe_translation_rejects_source_script_and_runaway_text():
    assert safe_translation("こんにちは", "Hello.")
    assert not safe_translation("こんにちは", "Hello こんにちは")
    assert not safe_translation("短い", "very " * 30)


class FakeLlama:
    def create_chat_completion(self, *, messages, **_kwargs):
        prompt = messages[-1]["content"]
        identifiers = [line[:5] for line in prompt.splitlines() if line.startswith("[")]
        # Force the four-line request to split, then return valid child batches.
        raw = "bad structure" if len(identifiers) > 2 else "\n".join(
            f"{identifier} English {index}" for index, identifier in enumerate(identifiers, 1)
        )
        return {"choices": [{"message": {"content": raw}}]}


def test_adaptive_batch_split_preserves_every_slot():
    result = translate_batch_adaptive(FakeLlama(), ["一", "二", "三", "四"])
    assert result == ["English 1", "English 2", "English 1", "English 2"]


def test_single_cue_preserves_wrapped_english_and_retries_explanation():
    class Responses:
        def __init__(self):
            self.outputs = iter(["Hello.\nExplanation: a greeting.", "It is raining.\nLet's go tomorrow."])

        def create_chat_completion(self, **kwargs):
            return {"choices": [{"message": {"content": next(self.outputs)}}]}

    assert translate_one(Responses(), "雨です。明日行きましょう。") == "It is raining. Let's go tomorrow."
