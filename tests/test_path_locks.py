import os
import subprocess
import sys
from pathlib import Path

import pytest

from atomic_io import atomic_text_writer
from path_locks import PathInUseError, path_locks


def child_process(path, code, **environment):
    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    return subprocess.Popen(
        [sys.executable, "-c", f"import sys\nsys.path.insert(0, {scripts!r})\n"
         "from pathlib import Path\nfrom path_locks import path_locks\n" + code, str(path)],
        env=dict(os.environ, PYTHONPATH=scripts, **environment), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def test_conflicting_process_fails_before_writing(tmp_path):
    target = tmp_path / "output.srt"
    with path_locks([target]):
        proc = child_process(target, "import sys\nwith path_locks([Path(sys.argv[1])]):\n Path(sys.argv[1]).write_text('bad')\n")
        _, error = proc.communicate(timeout=10)
        assert proc.returncode != 0 and "already in use" in error
        assert not target.exists()
    with path_locks([target]):
        pass


def test_portable_and_source_processes_share_locks_despite_different_temp_folders(tmp_path):
    target = tmp_path / "output.srt"
    portable_temp = tmp_path / "portable-cache"
    portable_temp.mkdir()
    with path_locks([target]):
        proc = child_process(target, "import sys\nwith path_locks([Path(sys.argv[1])]):\n pass\n",
                             TEMP=str(portable_temp), TMP=str(portable_temp), TMPDIR=str(portable_temp))
        _, error = proc.communicate(timeout=10)
        assert proc.returncode != 0 and "already in use" in error


def test_process_exit_releases_lock_and_failed_multi_acquire_releases_earlier_paths(tmp_path):
    target = tmp_path / "z.srt"
    other = tmp_path / "a.srt"
    proc = child_process(target, "import sys\nwith path_locks([Path(sys.argv[1])]):\n print('ready',flush=True)\n sys.stdin.readline()\n")
    try:
        assert proc.stdout.readline().strip() == "ready"
        with pytest.raises(PathInUseError):
            with path_locks([other, target]):
                pass
        with path_locks([other]):
            pass
    finally:
        proc.kill()
        proc.communicate(timeout=10)
    with path_locks([target]):
        pass


def test_nested_writer_cannot_corrupt_or_delete_another_writers_temp_file(tmp_path):
    target = tmp_path / "output.srt"
    with atomic_text_writer(target) as first:
        first.write("first")
        first.flush()
        partial = Path(first.name)
        assert partial != target.with_name(target.name + ".part")
        with pytest.raises(PathInUseError):
            with atomic_text_writer(target) as second:
                second.write("second")
        assert partial.is_file()
        first.write(" complete")
    assert target.read_text() == "first complete"
    assert not list(tmp_path.glob("*.part"))


def test_failed_writer_preserves_output_and_releases_lock(tmp_path):
    target = tmp_path / "output.srt"
    target.write_text("old")
    with pytest.raises(ValueError):
        with atomic_text_writer(target) as output:
            output.write("partial")
            raise ValueError("interrupted")
    assert target.read_text() == "old"
    assert not list(tmp_path.glob("*.part"))
    with atomic_text_writer(target) as output:
        output.write("retry")
    assert target.read_text() == "retry"


def test_pipeline_reserves_paths_before_opening_event_log_or_starting_stages(tmp_path, monkeypatch):
    import video_to_zh_srt as pipeline

    video = tmp_path / "sample.mp4"
    video.write_bytes(b"original input")
    output = tmp_path / "out/sample.zh-s.srt"
    events = tmp_path / "events.jsonl"
    monkeypatch.setattr(pipeline, "require_file", lambda *args: None)
    monkeypatch.setattr(pipeline.shutil, "which", lambda name: name)
    monkeypatch.setattr(sys, "argv", ["pipeline", str(video), "--output-dir", str(output.parent),
                                     "--work-dir", str(tmp_path / "work"), "--event-log", str(events)])
    with path_locks([output]):
        with pytest.raises(PathInUseError, match="already in use"):
            pipeline.main()
    assert not events.exists()
    assert not (tmp_path / "work").exists()
    assert video.read_bytes() == b"original input"
