from argparse import Namespace

import pytest

from make_bilingual_ass import (
    AssEntry,
    DEFAULT_GENDER_MODEL,
    ass_time,
    build_bilingual_ass,
    build_dialogue,
    classify_gender,
    escape_ass_text,
    gender_probabilities,
    parse_srt,
    style_for_gender,
)


def default_options():
    return Namespace(
        font="Arial",
        ja_font="Noto Sans JP",
        zh_font_size=36,
        ja_font_size=24,
        zh_colour="&H0000FFFF",
        ja_colour="&H00B4B4B4",
        male_colour="&H00FFBF00",
        female_colour="&H00B478FF",
        play_res_x=1280,
        play_res_y=720,
    )


def test_ass_time_uses_centiseconds():
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(3661.5) == "1:01:01.50"
    assert ass_time(-5) == "0:00:00.00"


def test_escape_ass_text_neutralizes_braces_and_newlines():
    assert escape_ass_text("a\nb") == "a\\Nb"
    assert escape_ass_text("{x}") == "(x)"


def test_build_dialogue_puts_chinese_on_top_and_switches_style():
    entry = AssEntry("1", 1.0, 3.0, "你好")
    line = build_dialogue(entry, "こんにちは")
    assert line == "Dialogue: 0,0:00:01.00,0:00:03.00,TL,,0,0,0,,你好\\N{\\rJA}こんにちは"


def test_build_dialogue_without_japanese_keeps_single_line():
    entry = AssEntry("1", 0.0, 1.0, "你好")
    assert build_dialogue(entry, "") == "Dialogue: 0,0:00:00.00,0:00:01.00,TL,,0,0,0,,你好"


def test_build_bilingual_ass_aligns_by_index():
    zh = [AssEntry("1", 0.0, 1.0, "你好"), AssEntry("2", 1.0, 2.0, "再见")]
    ja_by_index = {"1": "こんにちは", "2": "さようなら"}
    content = build_bilingual_ass(zh, ja_by_index, default_options())
    assert "[V4+ Styles]" in content
    assert "Style: TL,Arial,36,&H0000FFFF" in content
    assert "Style: JA,Noto Sans JP,24,&H00B4B4B4" in content
    assert "你好\\N{\\rJA}こんにちは" in content
    assert "再见\\N{\\rJA}さようなら" in content


def test_style_lines_match_format_field_count():
    # A malformed Style line (wrong field count) makes libass drop the whole cue,
    # so every Style row must have exactly as many fields as the Format row.
    content = build_bilingual_ass([], {}, default_options())
    style_format = next(line for line in content.splitlines() if line.startswith("Format: Name"))
    expected = len(style_format.split(":", 1)[1].split(","))
    for line in content.splitlines():
        if line.startswith("Style:"):
            fields = line.split(":", 1)[1].split(",")
            assert len(fields) == expected, line


def test_parse_srt_reads_index_times_and_text(tmp_path):
    srt = tmp_path / "x.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n你好\n\n2\n00:00:03,000 --> 00:00:04,500\n世界\n",
        encoding="utf-8",
    )
    entries = parse_srt(srt)
    assert [(e.index, e.start, e.end, e.text) for e in entries] == [
        ("1", 1.0, 3.0, "你好"),
        ("2", 3.0, 4.5, "世界"),
    ]


def test_parse_srt_preserves_display_line_breaks_for_ass(tmp_path):
    srt = tmp_path / "x.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:03,000\n第一行。\n第二行。\n", encoding="utf-8")

    entry = parse_srt(srt)[0]

    assert entry.text == "第一行。\n第二行。"
    assert "第一行。\\N第二行。\\N{\\rJA}日本語" in build_dialogue(entry, "日本語")


def test_parse_srt_ignores_timing_settings(tmp_path):
    srt = tmp_path / "x.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,000 position:50%\n你好\n",
        encoding="utf-8",
    )

    entries = parse_srt(srt)

    assert [(e.index, e.start, e.end, e.text) for e in entries] == [("1", 1.0, 3.0, "你好")]


def test_header_emits_speaker_styles():
    content = build_bilingual_ass([], {}, default_options())
    assert "Style: TL_M,Arial,36,&H00FFBF00" in content
    assert "Style: TL_F,Arial,36,&H00B478FF" in content


def test_style_for_gender_maps_to_styles():
    assert style_for_gender("M") == "TL_M"
    assert style_for_gender("F") == "TL_F"
    assert style_for_gender(None) == "TL"
    assert style_for_gender("") == "TL"


def test_build_dialogue_uses_given_style():
    entry = AssEntry("1", 1.0, 3.0, "你好")
    line = build_dialogue(entry, "こんにちは", "TL_F")
    assert line.startswith("Dialogue: 0,0:00:01.00,0:00:03.00,TL_F,,")


def test_build_bilingual_ass_assigns_style_per_gender():
    zh = [AssEntry("1", 0.0, 1.0, "他说"), AssEntry("2", 1.0, 2.0, "她说"), AssEntry("3", 2.0, 3.0, "谁")]
    genders = {"1": "M", "2": "F"}  # index 3 missing -> default ZH
    content = build_bilingual_ass(zh, {}, default_options(), genders)
    lines = [ln for ln in content.splitlines() if ln.startswith("Dialogue:")]
    assert ",TL_M,," in lines[0]
    assert ",TL_F,," in lines[1]
    assert ",TL,," in lines[2]


def test_classify_gender_thresholds_confidence():
    assert classify_gender(0.99, 0.01, 0.65) == "M"
    assert classify_gender(0.10, 0.90, 0.65) == "F"
    assert classify_gender(0.55, 0.45, 0.65) is None  # below floor -> uncoloured
    assert classify_gender(0.66, 0.34, 0.65) == "M"


@pytest.mark.skipif(not DEFAULT_GENDER_MODEL.exists(), reason="ECAPA gender model not downloaded")
def test_gender_probabilities_on_model_examples():
    # The model ships example1.wav (female) and example2.wav (male); use them as ground truth.
    sf = pytest.importorskip("soundfile")
    pytest.importorskip("torch")

    probs = {}
    for name, idx in [("example1.wav", "1"), ("example2.wav", "2")]:
        audio, sr = sf.read(str(DEFAULT_GENDER_MODEL / name))
        if getattr(audio, "ndim", 1) > 1:
            audio = audio.mean(axis=1)
        dur = len(audio) / float(sr)
        entry = AssEntry(idx, 0.0, dur, "x")
        p = gender_probabilities([entry], DEFAULT_GENDER_MODEL / name, DEFAULT_GENDER_MODEL)
        probs[idx] = p[idx]
    assert probs["1"][1] > probs["1"][0]  # example1 -> female
    assert probs["2"][0] > probs["2"][1]  # example2 -> male
