# jp2zh-video-subs v0.1.2

Bug-fix release for the Windows x64 CUDA portable build and source CLI/GUI. Model weights
and runtime dependencies are unchanged. Existing model downloads can be reused.

Changes since v0.1.1:

- Reject conflicting output/work paths across the entire GUI queue, including same-named
  videos in different folders. Resolve GUI relative paths before starting subprocesses.
- Keep fixed-height settings controls aligned under native Windows Qt styles.
- Validate event/cancellation paths before opening files. Reserve pipeline paths across
  processes and use independent temporary files for atomic subtitle writes.
- Fix rc.1's regression where one echoed vocalisation, kana-bearing name, empty translation,
  or repetition could abort a whole video. Preserve every cue and continue after retries,
  using conservative short-vocalisation rendering or a visible review marker as appropriate.
  Record unresolved candidates in `.review.json`; show the review count in all GUI languages.
  Apply per-cue recovery to experimental English output too. Real model/I/O failures still fail.
- Keep ASR/audio intermediates when review is needed, and do not cache reviewed output as
  a clean completed translation. Read-only video inputs can be shared across independent jobs.
- Include WhisperSeg weights in ASR resume identities and invalidate old Chinese
  translation cache schemas. The first resumed run may repeat ASR and translation.
- Match recursive subtitle layouts in the retiming tool, preserve native Windows drive
  paths, and apply drive-to-mount conversion only in WSL.
- Include the evidence-aware quality-report changes and evaluation tools developed after
  v0.1.1. The default Anime ASR and GalTransl translation models are unchanged.

Validation: 658 Linux automated tests and 185 targeted native Windows tests passed.
The failed video's frozen Japanese subtitles were retranslated with GalTransl on native
Windows / RTX 5080 in 34.42 seconds: all 336 cues retained their IDs and start times; one
short vocalisation was recovered and flagged for review. The installed Windows program
also completed the resumed pipeline, generated bilingual ASS, and passed user acceptance.
Detailed evidence is recorded in `docs/GUI_TEST_PLAN.md`.

Download all `jp2zh-video-subs-windows-x64-cuda-program.7z.*` volumes, place them in the same
folder, and extract starting from `.7z.001`. Follow `INSTALL-CN.txt` or `INSTALL-EN.txt`.
Use a new program folder when upgrading, then copy your existing `models` folder into it;
keep the old folder and any outputs you want to preserve until the new version is working.
The program archive includes no model weights, videos, subtitles, or personal settings.
`SHA256SUMS.parts` verifies individual volumes; `SHA256SUMS` verifies the reassembled archive.

Reviewed output is not guaranteed correct: inspect the `.review.json` report and visible
review markers. Experimental English output still needs manual review. Legacy translation
cache schemas and ASR manifests missing VAD model identities are invalidated on first resume.

## Historical v0.1.1 release notes

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
- A native Windows CUDA RTX 5090 system completed several full video workflows on this build.
  That GPU holds the configured batch, so no out-of-memory retry occurred and the backoff path
  was not exercised on hardware; it is covered by the simulated measurement above.
- The published program archive is rebuilt from the release commit, integrity-checked, freshly
  extracted, inspected for models, user data, settings, and development paths, and smoke-tested
  before upload.

Known scope:

- Experimental English output still requires manual review.
- Performance and memory use vary with the CPU, GPU, driver, model, and batch size.
- After a transient out-of-memory event the learned batch size is not raised again for the rest of
  the run, so a run that starts while another process holds VRAM may stay on a smaller batch.
- Long-video semantic-scene performance benchmarking and hosted CI are deferred.
