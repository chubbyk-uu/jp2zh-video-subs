import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from jp2zh_gui.app import acquire_instance_lock


def test_acquire_instance_lock_rejects_second_holder(tmp_path):
    lock_path = tmp_path / "config" / "jp2zh-video-subs.lock"
    first = acquire_instance_lock(lock_path)
    assert first is not None

    second = acquire_instance_lock(lock_path)
    assert second is None

    first.unlock()
    replacement = acquire_instance_lock(lock_path)
    assert replacement is not None
    replacement.unlock()
