# jp2zh-video-subs v0.1.0 Beta 5

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
Face with the relocatable root-level `hf.cmd`.

See `INSTALL-EN.txt` for complete English setup instructions or `INSTALL-CN.txt` for Chinese
instructions.

Changes since Beta 4:

- Replace the non-relocatable pip-generated `runtime\Scripts\hf.exe` instructions with a
  root-level `hf.cmd` wrapper that always launches the bundled Python by a path relative to the
  extracted application folder.
- Clear inference-only offline environment flags inside `hf.cmd` so model downloads can access
  Hugging Face while normal subtitle inference remains offline.
- Add a release extraction gate that actually executes `hf.cmd version` from the fresh
  extracted candidate. This prevents another build-machine absolute-path launcher from passing
  packaging validation.
- Update every English and Chinese setup command to use `hf.cmd download`.

Beta 4 is superseded because its setup instructions invoked pip's `hf.exe`, whose launcher
embedded the build-machine Python path and failed after moving the portable folder.

Validation completed during development:

- 403 automated tests pass together with Ruff, Python compilation, dependency consistency,
  shell syntax, and whitespace checks.
- The fresh extracted candidate executes `hf.cmd version` without referencing the build path.
- Beta 4's validated ASR, translation, resume, metadata, Windows CUDA, CLI, and GUI behaviour is
  otherwise unchanged.

Known scope:

- Experimental English output still requires manual review.
- Native CUDA validation currently covers one RTX 5080 system; other NVIDIA GPU and driver
  combinations remain beta feedback.
- Long-video semantic-scene performance benchmarking and hosted CI are deferred.
