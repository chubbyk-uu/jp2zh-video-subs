from anime_text_clean import anime_clean_batch, anime_clean_text, is_ellipsis_only


def test_ellipsis_only_dropped():
    for t in ["…", "‥", "...", "……", "…?", "…！", "…」", "…)", "  …  "]:
        assert anime_clean_text(t) == "", t
        assert is_ellipsis_only(t.strip()) is True, t


def test_ellipsis_with_content_kept():
    # 句中/句末的省略号保留；句首的省略号删掉(软起始伪迹)。
    assert anime_clean_text("あ…") == "あ…"          # 句末 …，保留，不补句号
    assert anime_clean_text("…あ") == "あ。"          # 句首 … 删掉，结尾补句号
    assert anime_clean_text("待って…") == "待って…"    # 句中/句末 …，保留
    assert is_ellipsis_only("あ…") is False
    assert is_ellipsis_only("…あ") is False


def test_bare_punct_not_ellipsis():
    # 无省略号/点的纯标点不算省略号伪迹（交给别的过滤）
    assert is_ellipsis_only("?") is False
    assert is_ellipsis_only("」") is False


def test_repetition_folded():
    assert anime_clean_text("だめだめだめだめ") == "だめ。"
    assert anime_clean_text("あはは、ダメダメダメですよ") == "あはは、ダメですよ。"


def test_emphasis_repetition_not_over_folded():
    # 只重复两次（总两单元）不折叠：真实台词的强调保留
    assert anime_clean_text("だめだめ") == "だめだめ。"


def test_ellipsis_runs_folded():
    assert anime_clean_text("待って……くる") == "待って…くる。"
    assert anime_clean_text("あ‥‥") == "あ…"


def test_sentence_ending_added_only_when_missing():
    assert anime_clean_text("おはよう") == "おはよう。"
    assert anime_clean_text("おはよう。") == "おはよう。"
    assert anime_clean_text("元気？") == "元気？"
    assert anime_clean_text("すごい！") == "すごい！"


def test_blank_input():
    assert anime_clean_text("") == ""
    assert anime_clean_text("   ") == ""


def test_batch():
    assert anime_clean_batch(["…", "おはよう", ""]) == ["", "おはよう。", ""]
