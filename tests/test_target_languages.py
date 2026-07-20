import pytest

from target_languages import (
    DEFAULT_BATCH_SIZE_BY_TRANSLATOR,
    DEFAULT_CONTEXT_SIZE,
    DEFAULT_WRAP_CHARS_BY_TARGET,
    TargetLanguage,
    output_language_suffix,
    resolve_translation_settings,
    translator_supports_target,
    validate_translator_target,
)


@pytest.mark.parametrize(
    ("language", "suffix"),
    (("zh-Hans", ".zh-s"), ("zh-Hant", ".zh-t"), ("en", ".en")),
)
def test_output_language_suffix(language, suffix):
    assert output_language_suffix(language) == suffix


def test_translator_target_compatibility_matrix():
    assert translator_supports_target("galtransl", TargetLanguage.SIMPLIFIED_CHINESE)
    assert translator_supports_target("sakura", TargetLanguage.TRADITIONAL_CHINESE)
    assert translator_supports_target("sugoi", TargetLanguage.ENGLISH)
    assert not translator_supports_target("sugoi", TargetLanguage.TRADITIONAL_CHINESE)
    assert not translator_supports_target("galtransl", TargetLanguage.ENGLISH)


def test_invalid_translator_target_has_actionable_error():
    with pytest.raises(ValueError, match=r"supported: en"):
        validate_translator_target("sugoi", "zh-Hans")


def test_translation_defaults_have_one_effective_source():
    gal = resolve_translation_settings("galtransl", "zh-Hans")
    assert gal.context_size == DEFAULT_CONTEXT_SIZE
    assert gal.batch_size == DEFAULT_BATCH_SIZE_BY_TRANSLATOR["galtransl"]
    assert gal.wrap_chars == DEFAULT_WRAP_CHARS_BY_TARGET[TargetLanguage.SIMPLIFIED_CHINESE]

    sugoi = resolve_translation_settings("sugoi", "en")
    assert sugoi.context_size is None
    assert sugoi.batch_size == DEFAULT_BATCH_SIZE_BY_TRANSLATOR["sugoi"]
    assert sugoi.wrap_chars == DEFAULT_WRAP_CHARS_BY_TARGET[TargetLanguage.ENGLISH]


@pytest.mark.parametrize("value", (0, 1))
def test_no_batch_values_normalize_to_one(value):
    assert resolve_translation_settings("sugoi", "en", batch_size=value).batch_size == 1


def test_negative_batch_is_rejected():
    with pytest.raises(ValueError, match="batch_size"):
        resolve_translation_settings("galtransl", "zh-Hans", batch_size=-1)
