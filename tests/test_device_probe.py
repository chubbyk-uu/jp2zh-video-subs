import jp2zh_gui.device_probe as device_probe


def test_probe_marks_missing_whisperseg_model_as_unverified(tmp_path):
    onnx_cuda, status, detail = device_probe.probe_onnx_device(tmp_path / "missing.onnx")

    assert onnx_cuda is False
    assert status == "missing_model"
    assert "WhisperSeg model missing:" in detail
