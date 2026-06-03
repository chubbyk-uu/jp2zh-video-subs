from argparse import Namespace

from make_bilingual_ass import (
    AssEntry,
    ass_time,
    build_bilingual_ass,
    build_dialogue,
    escape_ass_text,
    parse_srt,
)


def default_options():
    return Namespace(
        font="Arial",
        zh_font_size=36,
        ja_font_size=24,
        zh_colour="&H0000FFFF",
        ja_colour="&H00B4B4B4",
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
    assert line == "Dialogue: 0,0:00:01.00,0:00:03.00,ZH,,0,0,0,,你好\\N{\\rJA}こんにちは"


def test_build_dialogue_without_japanese_keeps_single_line():
    entry = AssEntry("1", 0.0, 1.0, "你好")
    assert build_dialogue(entry, "") == "Dialogue: 0,0:00:00.00,0:00:01.00,ZH,,0,0,0,,你好"


def test_build_bilingual_ass_aligns_by_index():
    zh = [AssEntry("1", 0.0, 1.0, "你好"), AssEntry("2", 1.0, 2.0, "再见")]
    ja_by_index = {"1": "こんにちは", "2": "さようなら"}
    content = build_bilingual_ass(zh, ja_by_index, default_options())
    assert "[V4+ Styles]" in content
    assert "Style: ZH,Arial,36,&H0000FFFF" in content
    assert "Style: JA,Arial,24,&H00B4B4B4" in content
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


def test_parse_srt_ignores_timing_settings(tmp_path):
    srt = tmp_path / "x.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,000 position:50%\n你好\n",
        encoding="utf-8",
    )

    entries = parse_srt(srt)

    assert [(e.index, e.start, e.end, e.text) for e in entries] == [("1", 1.0, 3.0, "你好")]
