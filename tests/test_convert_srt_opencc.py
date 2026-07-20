from pathlib import Path

from convert_srt_opencc import convert_srt, convert_srt_text


SRT = """1
00:00:01,000 --> 00:00:02,000
头发里面

2
00:00:03,000 --> 00:00:04,000
后台和开发
"""


class FakeConverter:
    def convert(self, text: str) -> str:
        return text.replace("头发", "頭髮").replace("后台", "後台").replace("开发", "開發")


def test_convert_srt_text_preserves_indices_and_timestamps():
    result = convert_srt_text(SRT, FakeConverter())
    assert "1\n00:00:01,000 --> 00:00:02,000\n頭髮裡面" not in result
    assert "1\n00:00:01,000 --> 00:00:02,000\n頭髮里面" in result
    assert "2\n00:00:03,000 --> 00:00:04,000\n後台和開發" in result
    assert result.endswith("\n")


def test_real_opencc_s2t_conversion(tmp_path: Path):
    source = tmp_path / "in.srt"
    output = tmp_path / "out.srt"
    source.write_text(SRT, encoding="utf-8")
    convert_srt(source, output)
    result = output.read_text(encoding="utf-8")
    # Generic s2t intentionally keeps general Traditional forms (裏/臺), rather
    # than applying Taiwan phrase conversion such as s2twp.
    assert "頭髮裏面" in result
    assert "後臺和開發" in result
    assert result.count("-->") == 2
