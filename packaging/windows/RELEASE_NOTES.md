# jp2zh-video-subs v0.1.0 Beta 4

Portable Windows x64 CUDA beta. Extract it and run the GUI without installing Python, FFmpeg,
or the CUDA Toolkit.

Requirements:

- Windows 10/11 x64
- An NVIDIA GPU with a working NVIDIA driver
- Sufficient VRAM, system memory, and disk space for the selected models

This release contains the application only. It includes no third-party model weights, user or
sample videos, subtitles, or similar content.

Download every `jp2zh-video-subs-windows-x64-cuda-program.7z.*` volume, place all volumes in the
same directory, and extract starting from `.7z.001`. Download the required models from Hugging
Face with the bundled `runtime\Scripts\hf.exe`.

See `INSTALL-EN.txt` for complete English setup instructions or `INSTALL-CN.txt` for Chinese
instructions.

Changes since Beta 3:

- Make `--resume` validate versioned audio, ASR, and translation manifests against upstream
  content, effective configuration, model identity, and output hashes before reusing artifacts.
- Reject unsafe or colliding input, output, intermediate, manifest, and temporary-file paths
  before a task starts, including case-insensitive Windows path collisions.
- Write ASR, metadata, translation, display-wrapped subtitles, and manifests through atomic
  temporary-file replacement.
- Cancel and reap look-ahead FFmpeg extraction when the active task fails, while preserving the
  original error and removing incomplete `.wav.part` files.
- Align production ASR metadata and quality-report contracts with schema v2 speech regions,
  alignment sentinel status, and recovery information.
- Apply shared startup-time validation across the pipeline, ASR, translation, ASS, quality
  report, and GUI so invalid values fail before models are loaded.
- License the original project code under MIT and include the project license in the portable
  folder and release extraction checks. Third-party and model licenses remain unchanged.
- Add shared local development configuration for pytest, Ruff, editor encoding, line endings,
  and indentation. CI remains intentionally deferred.

Validation completed during development:

- 401 automated tests pass together with Ruff, Python compilation, dependency consistency,
  shell syntax, and whitespace checks.
- A non-private 23-second Japanese sample completed Anime ASR, GalTransl translation, and the
  quality report in both the source environment and the Windows portable runtime.
- Exact resume reused audio, ASR, and translation; changing only translation settings reran
  translation, while changing ASR settings reran ASR and its downstream translation.
- Production metadata supplied real speech regions to the metadata quality-report backend.
- The Windows runtime uses Python 3.12.10 and PyTorch 2.11.0+cu128 and detected CUDA on the
  validated RTX 5080 system. An isolated-config GUI startup and clean shutdown also passed.

Known scope:

- Experimental English output still requires manual review.
- Native CUDA validation currently covers one RTX 5080 system; other NVIDIA GPU and driver
  combinations remain beta feedback.
- Long-video semantic-scene performance benchmarking and hosted CI are deferred.
