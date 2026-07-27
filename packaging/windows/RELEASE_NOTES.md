# jp2zh-video-subs v0.1.0

First stable portable Windows x64 CUDA release. Extract it and run the GUI without installing
Python, FFmpeg, or the CUDA Toolkit.

Requirements:

- Windows 10/11 x64
- An NVIDIA GPU with a working NVIDIA driver
- Sufficient VRAM, system memory, and disk space for the selected models

This release contains the application only. It includes no third-party model weights, user or
sample videos, subtitles, or similar content.

Download every `jp2zh-video-subs-windows-x64-cuda-program.7z.*` volume, place all volumes in the
same directory, and extract starting from `.7z.001`. Install the required models from the GUI's
**Manage models...** window or with the relocatable root-level `hf.cmd`.

See `INSTALL-EN.txt` for complete English setup instructions or `INSTALL-CN.txt` for Chinese
instructions.

Shell note: PowerShell users must set proxy variables with `$env:HTTPS_PROXY` /
`$env:HTTP_PROXY` and run the downloader as `.\hf.cmd`. Command Prompt users must use `set`
instead. The standalone installation guides attached to this release show both forms.

Highlights since Beta 5:

- Add a modal model manager with official Hugging Face and HF-Mirror sources, Xet or compatible
  resumable HTTP downloads, optional unauthenticated HTTP/HTTPS proxy settings, session progress,
  re-download, deletion, and separate shared-cache controls.
- Harden downloads with fixed upstream revisions, restricted filenames, path traversal and
  symlink checks, resumable-transfer identity metadata, size/content verification where available,
  atomic replacement, and automatic cleanup of stale partial files.
- Add Simplified Chinese, Traditional Chinese, and English interface languages, plus Simplified
  Chinese, Traditional Chinese, and experimental English subtitle targets.
- Add the Sugoi 14B Japanese-to-English backend and bundled OpenCC conversion for Traditional
  Chinese output. English translation remains experimental and should be reviewed manually.
- Make Anime ASR text generation use the selected batch size, with automatic out-of-memory batch
  splitting while preserving result order. The GUI now gives hardware-oriented batch presets and
  explains that weaker CPUs may benefit from a smaller batch.
- Improve device reporting, model completeness status, progress and cancellation behaviour,
  single-instance protection, runtime cleanup, settings layout, translated diagnostics, and the
  About dialog with an explicit application version.
- Keep the relocatable `hf.cmd` manual installer and verify it from a fresh extracted candidate.

Validation before publication:

- 477 automated tests pass together with Ruff and release-script checks.
- Batched Anime ASR A/B testing preserved recognized words across the tested batch sizes; the only
  observed output change was punctuation.
- The updated Windows package completed a full user-run subtitle workflow.
- Native Windows CUDA runs cover RTX 5080 and RTX 4080 Laptop 12 GB systems.
- The published program archive is rebuilt from the release commit, integrity-checked, freshly
  extracted, inspected for models, user data, settings, and development paths, and smoke-tested
  before upload.

Known scope:

- Experimental English output still requires manual review.
- Performance and memory use vary with the CPU, GPU, driver, model, and batch size.
- Long-video semantic-scene performance benchmarking and hosted CI are deferred.
