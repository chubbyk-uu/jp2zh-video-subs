"""Shared target-language contract for the CLI and desktop GUI."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TargetLanguage(StrEnum):
    SIMPLIFIED_CHINESE = "zh-Hans"
    TRADITIONAL_CHINESE = "zh-Hant"
    ENGLISH = "en"


TARGET_LANGUAGE_SUFFIXES = {
    TargetLanguage.SIMPLIFIED_CHINESE: ".zh-s",
    TargetLanguage.TRADITIONAL_CHINESE: ".zh-t",
    TargetLanguage.ENGLISH: ".en",
}

TRANSLATOR_TARGET_LANGUAGES = {
    "galtransl": frozenset((TargetLanguage.SIMPLIFIED_CHINESE, TargetLanguage.TRADITIONAL_CHINESE)),
    "sakura": frozenset((TargetLanguage.SIMPLIFIED_CHINESE, TargetLanguage.TRADITIONAL_CHINESE)),
    "sugoi": frozenset((TargetLanguage.ENGLISH,)),
}

DEFAULT_TRANSLATOR_BY_TARGET = {
    TargetLanguage.SIMPLIFIED_CHINESE: "galtransl",
    TargetLanguage.TRADITIONAL_CHINESE: "galtransl",
    TargetLanguage.ENGLISH: "sugoi",
}

DEFAULT_CONTEXT_SIZE = 6
DEFAULT_BATCH_SIZE_BY_TRANSLATOR = {
    "galtransl": 8,
    "sugoi": 10,
}
DEFAULT_WRAP_CHARS_BY_TARGET = {
    TargetLanguage.SIMPLIFIED_CHINESE: 20,
    TargetLanguage.TRADITIONAL_CHINESE: 20,
    TargetLanguage.ENGLISH: 60,
}


@dataclass(frozen=True)
class EffectiveTranslationSettings:
    context_size: int | None
    batch_size: int | None
    wrap_chars: int


def target_language(value: str | TargetLanguage) -> TargetLanguage:
    return value if isinstance(value, TargetLanguage) else TargetLanguage(value)


def output_language_suffix(value: str | TargetLanguage) -> str:
    return TARGET_LANGUAGE_SUFFIXES[target_language(value)]


def translator_supports_target(translator: str, target: str | TargetLanguage) -> bool:
    return target_language(target) in TRANSLATOR_TARGET_LANGUAGES.get(translator, ())


def resolve_translation_settings(
    translator: str,
    target: str | TargetLanguage,
    *,
    context_size: int | None = None,
    batch_size: int | None = None,
    wrap_chars: int | None = None,
) -> EffectiveTranslationSettings:
    """Resolve defaults and normalize the equivalent no-batch values 0 and 1."""
    resolved_target = target_language(target)
    resolved_context = None if translator == "sugoi" else (
        DEFAULT_CONTEXT_SIZE if context_size is None else context_size
    )
    if translator in DEFAULT_BATCH_SIZE_BY_TRANSLATOR:
        raw_batch = DEFAULT_BATCH_SIZE_BY_TRANSLATOR[translator] if batch_size is None else batch_size
        if raw_batch < 0:
            raise ValueError("batch_size must be >= 0")
        resolved_batch = max(1, raw_batch)
    else:
        resolved_batch = None
    resolved_wrap = DEFAULT_WRAP_CHARS_BY_TARGET[resolved_target] if wrap_chars is None else wrap_chars
    return EffectiveTranslationSettings(resolved_context, resolved_batch, resolved_wrap)


def validate_translator_target(translator: str, target: str | TargetLanguage) -> None:
    resolved = target_language(target)
    if translator_supports_target(translator, resolved):
        return
    supported_targets = TRANSLATOR_TARGET_LANGUAGES.get(translator, ())
    supported = ", ".join(
        item.value for item in TargetLanguage if item in supported_targets
    ) or "none"
    raise ValueError(
        f"Translator '{translator}' does not support target language '{resolved.value}' "
        f"(supported: {supported})."
    )
