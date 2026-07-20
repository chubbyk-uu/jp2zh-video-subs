# jp2zh-video-subs v0.1.0 Beta 3

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

Changes since Beta 2:

- Add Simplified Chinese, Traditional Chinese, and English GUI interface languages.
- Rename the launcher to the language-neutral `jp2zh-subtitle-tool.exe`.
- Add independent Simplified Chinese and Traditional Chinese subtitle output with `.zh-s` and
  `.zh-t` file suffixes. Traditional Chinese uses bundled OpenCC `s2t` conversion.
- Add experimental Japanese-to-English subtitle output through Sugoi 14B Ultra, with `.en`
  suffixes, validated numbered batching, safe fallback, and word-aware wrapping. Manual review
  is recommended for English output.
- Restrict translation-model choices and advanced controls to combinations supported by the
  selected subtitle language and backend.
- Improve GUI sizing, model/settings alignment, native drop-down behaviour, localized model
  status messages, and the user-resizable log panel.
- Include current Chinese and English setup guides inside the extracted application folder.

Validation completed during development:

- 384 automated tests pass, including CLI, pipeline, GUI i18n/offscreen, subtitle conversion,
  Sugoi batching, and Windows release-script checks.
- Native Windows CUDA runs completed for Simplified Chinese, Traditional Chinese, and
  experimental English on an RTX 5080 test system.
