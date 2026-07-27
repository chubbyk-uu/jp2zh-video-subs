import os
from pathlib import Path
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

import jp2zh_gui.model_download as model_download_module
from jp2zh_gui.model_download import ModelDownloadController, ModelDownloadDialog
from model_catalog import MODEL_DOWNLOAD_SPECS, ModelDownloadSpec


class FakeDownloadController(QObject):
    event_received = Signal(object)
    log_received = Signal(str)
    finished = Signal(bool, bool)

    def __init__(self) -> None:
        super().__init__()
        self.is_running = False
        self.started_with: (
            tuple[list[str], str, Path, bool, str | None, str] | None
        ) = None
        self.cancelled = False

    def start(
        self,
        keys: list[str],
        source: str,
        root: Path,
        *,
        force: bool = False,
        proxy: str | None = None,
        download_backend: str = "auto",
    ) -> None:
        self.started_with = (
            keys,
            source,
            root,
            force,
            proxy,
            download_backend,
        )
        self.is_running = True

    def cancel(self) -> None:
        self.cancelled = True


def application() -> QApplication:
    return QApplication.instance() or QApplication([])


def settings_at(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "model-manager.ini"), QSettings.Format.IniFormat)


def make_dialog(
    tmp_path: Path,
    *,
    current: tuple[str, ...] = ("anime-whisper", "galtransl-7b"),
) -> tuple[ModelDownloadDialog, FakeDownloadController]:
    controller = FakeDownloadController()
    dialog = ModelDownloadDialog(
        None,
        current_model_keys=current,
        settings=settings_at(tmp_path),
        root=tmp_path,
        controller=controller,
    )
    return dialog, controller


def test_dialog_is_modal_and_preselects_current_missing_models(tmp_path):
    application()
    dialog, _controller = make_dialog(tmp_path)
    try:
        assert dialog.windowModality() == Qt.WindowModality.ApplicationModal
        assert dialog._selected_keys() == ["anime-whisper", "galtransl-7b"]
    finally:
        dialog.close()


def test_new_catalog_entry_uses_generic_purpose_text(tmp_path, monkeypatch):
    application()
    new_spec = ModelDownloadSpec(
        key="brand-new",
        name="Brand New",
        repo_id="owner/repo",
        local_dir="models/brand-new",
        required_files=("model.bin",),
        filenames=("model.bin",),
        revision="a" * 40,
    )
    monkeypatch.setattr(
        model_download_module,
        "MODEL_DOWNLOAD_SPECS",
        (*MODEL_DOWNLOAD_SPECS, new_spec),
    )

    dialog, _controller = make_dialog(tmp_path, current=())
    try:
        row = dialog._rows_by_key["brand-new"]
        assert dialog.table.item(row, 2).text() == "Model download"
    finally:
        dialog.close()


def test_installed_models_are_selectable_but_not_preselected(tmp_path):
    application()
    anime = next(spec for spec in MODEL_DOWNLOAD_SPECS if spec.key == "anime-whisper")
    for path in anime.required_paths(tmp_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"installed")

    dialog, _controller = make_dialog(tmp_path)
    try:
        row = dialog._rows_by_key["anime-whisper"]
        item = dialog.table.item(row, 0)
        assert item.flags() & Qt.ItemFlag.ItemIsUserCheckable
        assert item.checkState() == Qt.CheckState.Unchecked
        assert dialog._selected_keys() == ["galtransl-7b"]
    finally:
        dialog.close()


def test_selected_models_are_submitted_in_catalog_order(tmp_path):
    application()
    dialog, controller = make_dialog(tmp_path, current=())
    try:
        requested = {"sugoi-14b", "whisperseg", "sakura-14b"}
        dialog._set_checked_keys(requested)
        dialog.source_combo.setCurrentIndex(dialog.source_combo.findData("mirror"))
        dialog._start_download(force=False)

        assert controller.started_with == (
            ["whisperseg", "sakura-14b", "sugoi-14b"],
            "mirror",
            tmp_path,
            False,
            None,
            "auto",
        )
        assert not dialog.start_button.isEnabled()
        assert dialog.cancel_button.isEnabled()
    finally:
        controller.is_running = False
        dialog.close()


def test_source_selection_is_persisted(tmp_path):
    application()
    settings = settings_at(tmp_path)
    first = ModelDownloadDialog(
        None,
        current_model_keys=(),
        settings=settings,
        root=tmp_path,
        controller=FakeDownloadController(),
    )
    try:
        first.source_combo.setCurrentIndex(first.source_combo.findData("mirror"))
        settings.sync()
        assert settings.value("model_download_source") == "mirror"
    finally:
        first.close()

    second = ModelDownloadDialog(
        None,
        current_model_keys=(),
        settings=settings,
        root=tmp_path,
        controller=FakeDownloadController(),
    )
    try:
        assert second.source_combo.currentData() == "mirror"
    finally:
        second.close()


def test_xet_note_uses_checkbox_right_side_and_mirror_note_falls_back(tmp_path):
    application()
    dialog, _controller = make_dialog(tmp_path, current=())
    try:
        assert dialog.source_label.minimumWidth() == 0
        assert "Xet progress updates in batches" in dialog.source_note.text()

        dialog.native_backend_check.setChecked(False)
        assert dialog.source_note.text() == ""

        dialog.source_combo.setCurrentIndex(
            dialog.source_combo.findData("mirror")
        )
        assert "Third-party mirror" in dialog.source_note.text()
        assert "Third-party mirror" in dialog.source_combo.toolTip()

        dialog.native_backend_check.setChecked(True)
        assert "Xet progress updates in batches" in dialog.source_note.text()
        assert "Third-party mirror" in dialog.source_combo.toolTip()
    finally:
        dialog.close()


def test_proxy_selection_is_validated_persisted_and_submitted(tmp_path):
    application()
    dialog, controller = make_dialog(tmp_path, current=())
    try:
        dialog._set_checked_keys({"whisperseg"})
        dialog.proxy_check.setChecked(True)
        dialog.proxy_edit.setText("http://127.0.0.1:7890")
        dialog._start_download(force=False)

        assert controller.started_with == (
            ["whisperseg"],
            "official",
            tmp_path,
            False,
            "http://127.0.0.1:7890",
            "auto",
        )
        assert dialog.settings.value("model_download_proxy_enabled", False, bool)
        assert (
            dialog.settings.value("model_download_proxy_url")
            == "http://127.0.0.1:7890"
        )
    finally:
        controller.is_running = False
        dialog.close()


def test_proxy_rejects_credentials_and_does_not_persist_them(tmp_path):
    application()
    settings = settings_at(tmp_path)
    dialog = ModelDownloadDialog(
        None,
        current_model_keys=(),
        settings=settings,
        root=tmp_path,
        controller=FakeDownloadController(),
    )
    try:
        dialog.proxy_check.setChecked(True)
        dialog.proxy_edit.setText("http://127.0.0.1:7890")
        settings.sync()
        dialog.proxy_edit.setText("http://user:secret@127.0.0.1:7890")
        settings.sync()

        assert (
            settings.value("model_download_proxy_url")
            == "http://127.0.0.1:7890"
        )
        with pytest.raises(ValueError, match="Authenticated proxies"):
            dialog._validated_proxy()
        assert "no authentication" in dialog.proxy_check.text()
    finally:
        dialog.close()


@pytest.mark.parametrize(
    "value",
    [
        "socks5://127.0.0.1:7890",
        "http://127.0.0.1",
        "http://127.0.0.1:7890/path",
        "http://127.0.0.1:7890?query=yes",
    ],
)
def test_proxy_rejects_unsupported_endpoint_shapes(tmp_path, value):
    application()
    dialog, _controller = make_dialog(tmp_path, current=())
    try:
        dialog.proxy_check.setChecked(True)
        dialog.proxy_edit.setText(value)
        with pytest.raises(ValueError):
            dialog._validated_proxy()
    finally:
        dialog.close()


def test_download_details_explain_state_and_record_events(tmp_path):
    application()
    dialog, _controller = make_dialog(tmp_path)
    try:
        assert "after a task starts" in dialog.log_edit.toPlainText()
        dialog._apply_event({"type": "model_query_started", "model": "anime-whisper"})
        assert "Querying metadata: Anime Whisper" in dialog.log_edit.toPlainText()
    finally:
        dialog.close()


def test_backend_fallback_is_visible_without_opening_details(tmp_path):
    application()
    dialog, _controller = make_dialog(tmp_path)
    try:
        dialog._apply_event(
            {
                "type": "backend_fallback",
                "model": "anime-whisper",
                "message": "native failed",
            }
        )
        assert (
            dialog.queue_status_label.text()
            == "Hugging Face/Xet failed; switched to compatibility HTTP."
        )
        assert "native failed" in dialog.log_edit.toPlainText()
    finally:
        dialog.close()


def test_compatibility_download_mode_is_persisted_and_submitted(tmp_path):
    application()
    settings = settings_at(tmp_path)
    controller = FakeDownloadController()
    dialog = ModelDownloadDialog(
        None,
        current_model_keys=(),
        settings=settings,
        root=tmp_path,
        controller=controller,
    )
    try:
        dialog._set_checked_keys({"whisperseg"})
        dialog.native_backend_check.setChecked(False)
        dialog._start_download(force=False)

        assert controller.started_with == (
            ["whisperseg"],
            "official",
            tmp_path,
            False,
            None,
            "compat",
        )
        assert not settings.value("model_download_prefer_native", True, bool)
        assert "compatibility HTTP only" in dialog.log_edit.toPlainText()
    finally:
        controller.is_running = False
        dialog.close()


def test_progress_and_completion_events_update_the_dialog(tmp_path):
    application()
    dialog, controller = make_dialog(tmp_path)
    changed = []
    dialog.models_changed.connect(lambda: changed.append(True))
    try:
        dialog._apply_event(
            {
                "type": "queue_started",
                "model_count": 2,
                "overall_total_bytes": 200,
            }
        )
        dialog._apply_event(
            {
                "type": "model_started",
                "model": "anime-whisper",
                "index": 1,
                "count": 2,
                "total_bytes": 100,
            }
        )
        dialog._apply_event(
            {
                "type": "progress",
                "downloaded_bytes": 50,
                "total_bytes": 100,
                "overall_downloaded_bytes": 50,
                "overall_total_bytes": 200,
                "speed_bytes_per_second": 10,
            }
        )

        assert dialog.model_progress.value() == 500
        assert dialog.overall_progress.value() == 250
        assert "50 B / 100 B" in dialog.transfer_label.text()
        assert "average 10 B/s" in dialog.transfer_label.text()

        controller.is_running = False
        dialog._download_finished(True, False)
        assert changed == [True]
    finally:
        dialog.close()


def test_cancel_requests_controller_and_keeps_resume_message(tmp_path):
    application()
    dialog, controller = make_dialog(tmp_path)
    try:
        dialog.overall_progress.setRange(0, 0)
        dialog.model_progress.setRange(0, 0)
        controller.is_running = True
        dialog._cancel_download()
        assert controller.cancelled
        assert "partial files" in dialog.queue_status_label.text()

        controller.is_running = False
        dialog._download_finished(False, True)
        assert "partial files were kept" in dialog.queue_status_label.text()
        assert dialog.overall_progress.maximum() == 1000
        assert dialog.overall_progress.value() == 0
        assert dialog.model_progress.maximum() == 1000
        assert dialog.model_progress.value() == 0
    finally:
        dialog.close()


def test_success_settles_unknown_progress_as_complete(tmp_path):
    application()
    dialog, controller = make_dialog(tmp_path)
    try:
        dialog.overall_progress.setRange(0, 0)
        dialog.model_progress.setRange(0, 0)
        controller.is_running = False
        dialog._download_finished(True, False)
        assert dialog.overall_progress.maximum() == 1000
        assert dialog.overall_progress.value() == 1000
        assert dialog.model_progress.maximum() == 1000
        assert dialog.model_progress.value() == 1000
    finally:
        dialog.close()


def test_unreported_process_failure_shows_generic_error(tmp_path):
    application()
    dialog, controller = make_dialog(tmp_path)
    try:
        controller.is_running = False
        dialog._download_finished(False, False)
        assert dialog.queue_status_label.text() == "Model download failed."
    finally:
        dialog.close()


def test_redownload_submits_installed_model_with_force(tmp_path):
    application()
    spec = next(spec for spec in MODEL_DOWNLOAD_SPECS if spec.key == "whisperseg")
    for path in spec.required_paths(tmp_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"installed")
    dialog, controller = make_dialog(tmp_path, current=())
    try:
        dialog._set_checked_keys({"whisperseg"})
        dialog._start_download(force=True)
        assert controller.started_with == (
            ["whisperseg"],
            "official",
            tmp_path,
            True,
            None,
            "auto",
        )
    finally:
        controller.is_running = False
        dialog.close()


def test_delete_requires_confirmation_and_removes_selected_directory(
    tmp_path,
    monkeypatch,
):
    application()
    spec = next(spec for spec in MODEL_DOWNLOAD_SPECS if spec.key == "whisperseg")
    destination = spec.destination(tmp_path)
    destination.mkdir(parents=True)
    (destination / "model.onnx").write_bytes(b"installed")
    dialog, _controller = make_dialog(tmp_path, current=())
    changed = []
    dialog.models_changed.connect(lambda: changed.append(True))
    try:
        dialog._set_checked_keys({"whisperseg"})
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *_args: QMessageBox.StandardButton.Cancel,
        )
        dialog._delete_selected()
        assert destination.is_dir()

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *_args: QMessageBox.StandardButton.Yes,
        )
        dialog._delete_selected()
        assert not destination.exists()
        assert changed == [True]
        assert "1 models deleted" in dialog.queue_status_label.text()
    finally:
        dialog.close()


def test_shared_xet_cache_requires_confirmation_and_keeps_installed_models(
    tmp_path,
    monkeypatch,
):
    application()
    spec = next(spec for spec in MODEL_DOWNLOAD_SPECS if spec.key == "whisperseg")
    installed = spec.required_paths(tmp_path)[0]
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"installed")
    cache = tmp_path / "cache" / "huggingface" / "xet"
    (cache / "chunks").mkdir(parents=True)
    (cache / "chunks" / "chunk.bin").write_bytes(b"x" * 20)
    dialog, _controller = make_dialog(tmp_path, current=())
    monkeypatch.setattr(dialog, "_xet_cache_path", lambda: cache)
    try:
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *_args: QMessageBox.StandardButton.Cancel,
        )
        dialog._clear_xet_cache()
        assert (cache / "chunks" / "chunk.bin").exists()

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *_args: QMessageBox.StandardButton.Yes,
        )
        dialog._clear_xet_cache()
        assert cache.is_dir()
        assert not any(cache.iterdir())
        assert installed.read_bytes() == b"installed"
        assert dialog.queue_status_label.text() == "Shared Xet cache cleared."
    finally:
        dialog.close()


def test_xet_cache_management_refuses_symbolic_link(tmp_path, monkeypatch):
    application()
    target = tmp_path / "elsewhere"
    target.mkdir()
    cache = tmp_path / "cache" / "huggingface" / "xet"
    cache.parent.mkdir(parents=True)
    cache.symlink_to(target, target_is_directory=True)
    dialog, _controller = make_dialog(tmp_path, current=())
    monkeypatch.setattr(dialog, "_xet_cache_path", lambda: cache)
    try:
        with pytest.raises(RuntimeError, match="symbolic-link"):
            dialog._safe_xet_cache_path()
    finally:
        dialog.close()


def test_delete_refuses_catalog_path_outside_models(tmp_path):
    application()
    dialog, _controller = make_dialog(tmp_path, current=())
    unsafe = ModelDownloadSpec(
        key="unsafe",
        name="Unsafe",
        repo_id="owner/repo",
        local_dir="../outside",
        required_files=("model.bin",),
    )
    try:
        with pytest.raises(RuntimeError, match="outside the models folder"):
            dialog._safe_model_destination(unsafe)
    finally:
        dialog.close()


def test_controller_reads_structured_events_and_clears_offline_flags(tmp_path):
    application()
    helper = tmp_path / "fake-download.py"
    helper.write_text(
        "import json, os, sys\n"
        "print(json.dumps({'type': 'probe', "
        "'hf_offline': os.environ.get('HF_HUB_OFFLINE'), "
        "'transformers_offline': os.environ.get('TRANSFORMERS_OFFLINE'), "
        "'http_proxy': os.environ.get('HTTP_PROXY'), "
        "'https_proxy': os.environ.get('HTTPS_PROXY'), "
        "'all_proxy': os.environ.get('ALL_PROXY')}))\n"
        "print('diagnostic line', file=sys.stderr)\n",
        encoding="utf-8",
    )
    controller = ModelDownloadController(
        python_executable=sys.executable,
        download_script=helper,
    )
    events: list[dict[str, object]] = []
    logs: list[str] = []
    results: list[tuple[bool, bool]] = []
    loop = QEventLoop()
    controller.event_received.connect(events.append)
    controller.log_received.connect(logs.append)
    controller.finished.connect(lambda success, cancelled: results.append((success, cancelled)))
    controller.finished.connect(loop.quit)

    changed_environment = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HTTP_PROXY": "http://inherited.example:8080",
        "HTTPS_PROXY": "http://inherited.example:8080",
        "ALL_PROXY": "socks5://inherited.example:1080",
    }
    previous_environment = {
        name: os.environ.get(name) for name in changed_environment
    }
    os.environ.update(changed_environment)
    try:
        controller.start(["anime-whisper"], "official", tmp_path)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
    finally:
        for name, previous in previous_environment.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous

    assert results == [(True, False)]
    assert events == [
        {
            "type": "probe",
            "hf_offline": None,
            "transformers_offline": None,
            "http_proxy": None,
            "https_proxy": None,
            "all_proxy": None,
        }
    ]
    assert "diagnostic line" in "".join(logs)
