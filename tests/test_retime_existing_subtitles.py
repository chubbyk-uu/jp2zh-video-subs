from pathlib import Path

from retime_existing_subtitles import process_video, subtitle_paths


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
