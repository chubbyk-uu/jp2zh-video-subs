# jp2zh-video-subs v0.1.1

Bug-fix release for the portable Windows x64 CUDA build. Extract it and run the GUI without
installing Python, FFmpeg, or the CUDA Toolkit. There are no command-line, configuration, or
output format changes since `v0.1.0`; upgrading is a straight replacement of the extracted
program directory.

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

Fixes since v0.1.0:

- Keep the reduced Anime ASR text-generation batch size after an out-of-memory retry. Previously
  each batch restarted from the configured size, so a GPU that could not hold the default batch
  repeated the same shrink cascade for every batch instead of once per run. Recognized text and
  cue order are unchanged; only the number of out-of-memory retries drops.
- Stop the model manager from skipping an incomplete model download. Download completeness is now
  judged against every file the downloader selects, not only the files inference requires, so a
  transfer interrupted after the required files were already in place is resumed instead of being
  reported as installed. Whether a model can run is still judged by the required files alone, so
  an existing usable model is never blocked by an unrelated partial file.

Validation before publication:

- 480 automated tests pass together with Ruff and release-script checks.
- The out-of-memory backoff was measured against a simulated GPU limit: with 120 items and a
  starting batch of 24 against a device that holds 6, out-of-memory retries drop from 15 to 2,
  and cue order is unchanged. A device that holds the full batch adds no retries.
- Model install state and model download state were verified separately for a model whose
  required files are complete while another selected file is still partial or missing.
- The published program archive is rebuilt from the release commit, integrity-checked, freshly
  extracted, inspected for models, user data, settings, and development paths, and smoke-tested
  before upload.

Known scope:

- Experimental English output still requires manual review.
- Performance and memory use vary with the CPU, GPU, driver, model, and batch size.
- After a transient out-of-memory event the learned batch size is not raised again for the rest of
  the run, so a run that starts while another process holds VRAM may stay on a smaller batch.
- Long-video semantic-scene performance benchmarking and hosted CI are deferred.
