from retime_existing_subtitles import process_video, subtitle_paths


def test_windows_native_paths_are_preserved(monkeypatch):
    from pathlib import PureWindowsPath
    from types import SimpleNamespace
    import retime_existing_subtitles as retime

    monkeypatch.setattr(retime, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(retime, "Path", PureWindowsPath)
    path = PureWindowsPath(r"E:\videos\sample.mp4")
    assert retime.wsl_path(str(path)) == path
    assert retime.wsl_path(str(path)).drive == "E:"


def test_windows_drive_conversion_is_only_enabled_in_wsl(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    import retime_existing_subtitles as retime

    monkeypatch.setattr(retime, "os", SimpleNamespace(name="posix", environ={}))
    monkeypatch.setattr(retime.platform, "release", lambda: "linux-generic")
    path = r"E:\videos\sample.mp4"
    assert retime.wsl_path(path) == Path(path)
    retime.os.environ["WSL_DISTRO_NAME"] = "Ubuntu"
    assert retime.wsl_path(path).as_posix() == "/mnt/e/videos/sample.mp4"
    retime.os.environ.clear()
    monkeypatch.setattr(retime.platform, "release", lambda: "6.6.87-microsoft-standard-WSL2")
    assert retime.wsl_path(path).as_posix() == "/mnt/e/videos/sample.mp4"


def test_process_video_writes_retimed_srt_and_copied_ass(tmp_path):
    video_dir = tmp_path / "videos"
    output_dir = tmp_path / "outputs"
    work_dir = tmp_path / "work"
    stem = "sample"
    video_dir.mkdir()
    output_dir.mkdir()
    (work_dir / stem).mkdir(parents=True)
    video = video_dir / f"{stem}.mp4"
    video.write_bytes(b"")
    (output_dir / f"{stem}.zh.srt").write_text(
        "1\n00:00:01,000 --> 00:00:01,400\n你好\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n世界\n",
        encoding="utf-8",
    )
    (work_dir / stem / f"{stem}.ja.srt").write_text(
        "1\n00:00:01,000 --> 00:00:01,400\nこんにちは\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n世界\n",
        encoding="utf-8",
    )

    paths = subtitle_paths(video, output_dir, work_dir)
    assert paths is not None

    class Options:
        lead_out_seconds = 0.5
        min_display_seconds = 1.5
        min_gap_seconds = 0.04
        font = "Arial"
        ja_font = "Noto Sans JP"
        zh_font_size = 36
        ja_font_size = 24
        zh_colour = "&H0000FFFF"
        ja_colour = "&H00B4B4B4"
        play_res_x = 1280
        play_res_y = 720

    process_video(paths, Options(), dry_run=False, copy_to_video_dir=True)

    assert (output_dir / f"{stem}.retimed.zh-s.srt").read_text(encoding="utf-8").startswith(
        "1\n00:00:01,000 --> 00:00:02,500\n你好\n"
    )
    ass = (output_dir / f"{stem}.retimed.zh-s.ass").read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:01.00,0:00:02.50" in ass
    assert (video.parent / f"{stem}.zh-s.ass").read_text(encoding="utf-8") == ass


def test_recursive_retime_keeps_same_named_videos_and_subtitles_separate(tmp_path, monkeypatch, capsys):
    import sys
    import retime_existing_subtitles as retime
    from video_to_zh_srt import output_path_for, work_dir_for

    inputs, outputs, work = (tmp_path / name for name in ("videos", "outputs", "work"))
    for folder, zh, ja in (("a", "你好", "こんにちは"), ("b", "再见", "さようなら")):
        video = inputs / folder / "sample.mp4"
        video.parent.mkdir(parents=True)
        video.touch()
        srt = output_path_for(video, inputs, outputs, True)
        ja_srt = work_dir_for(video, inputs, work, True) / "sample.ja.srt"
        for path, text in ((srt, zh), (ja_srt, ja)):
            path.parent.mkdir(parents=True)
            path.write_text(f"1\n00:00:01,000 --> 00:00:02,000\n{text}\n\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["retime", str(inputs), "--recursive", "--output-dir", str(outputs),
                                     "--work-dir", str(work), "--no-copy-to-video-dir"])
    retime.main()
    assert "processed=2, skipped=0" in capsys.readouterr().out
    for folder, zh, ja in (("a", "你好", "こんにちは"), ("b", "再见", "さようなら")):
        ass = (outputs / folder / "sample.retimed.zh-s.ass").read_text(encoding="utf-8")
        assert zh in ass and ja in ass
    assert not (outputs / "sample.retimed.zh-s.ass").exists()


def test_recursive_retime_does_not_fall_back_to_unrelated_flat_subtitles(tmp_path):
    inputs, outputs, work = (tmp_path / name for name in ("videos", "outputs", "work"))
    video = inputs / "nested" / "sample.mp4"
    video.parent.mkdir(parents=True)
    video.touch()
    outputs.mkdir()
    (outputs / "sample.zh-s.srt").touch()
    (work / "sample").mkdir(parents=True)
    (work / "sample/sample.ja.srt").touch()
    assert subtitle_paths(video, outputs, work, input_path=inputs, recursive=True) is None
