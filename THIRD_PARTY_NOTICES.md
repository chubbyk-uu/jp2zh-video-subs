# Third-Party Notices

This project incorporates code adapted from third-party open-source projects.

## Optional GUI dependency

The optional desktop GUI uses PySide6. The locally verified PySide6 6.11.1 package metadata
declares `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`. The Windows portable development
and release-candidate folders include the LGPLv3/GPLv3 texts, Qt for Python third-party license
page, and Qt's LGPL obligations page under `licenses/qt-pyside/`. Any published archive must
retain those files and satisfy the selected license's redistribution requirements.

## Bundled FFmpeg

The Windows portable development folder bundles the static FFmpeg 8.1.2 essentials build from
gyan.dev. That build identifies itself as GPLv3. The packaging script copies its `LICENSE` and
`README.txt` files into `licenses/ffmpeg/`; the release-candidate program archive retains them.
Published archives must continue to include them and comply with
the build's corresponding source and license obligations.

## OpenCC

Traditional-Chinese subtitle output uses OpenCC 1.4.1 and its bundled dictionaries. OpenCC is
distributed under the Apache License 2.0. The Windows portable program archive includes the
upstream `LICENSE` and `AUTHORS` files under `licenses/opencc/`.

## WhisperJAV

`scripts/anime_text_clean.py` and `scripts/alignment_recovery.py` are adapted from
[WhisperJAV](https://github.com/meizhong986/WhisperJAV):

- `anime_text_clean.py` — adapted from
  `whisperjav/modules/subtitle_pipeline/cleaners/anime_whisper.py` (`AnimeWhisperCleaner`).
- `alignment_recovery.py` — adapted from `whisperjav/modules/alignment_sentinel.py`
  (collapse detection thresholds and VAD-guided / proportional redistribution).
- `whisperseg_vad.py` — adapted from
  `whisperjav/modules/speech_segmentation/backends/whisperseg.py` and
  `.../backends/ten.py::group_segments`. Its ONNX inference state machine is in turn
  adapted from `TransWithAI/Whisper-Vad-EncDec-ASMR-onnx/inference.py` (MIT).
- `semantic_scene.py` — adapted from
  `whisperjav/vendor/semantic_audio_clustering.py` (StreamFeatureExtractor +
  SemanticSegmenter: acoustic-texture clustering, silence snapping, full coverage).

WhisperJAV is distributed under the MIT License:

```
MIT License

Copyright (c) 2023 meizhong986

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Models

- **anime-whisper** (`litagin/anime-whisper`) — a Whisper large-v2 fine-tune used as the
  default Anime text source; upstream declares MIT.
- **Whisper-Vad-EncDec-ASMR-onnx** (`TransWithAI/...`) — default WhisperSeg VAD; upstream
  declares MIT.
- **Qwen3-ForcedAligner-0.6B** (`Qwen/...`) — forced alignment for the default Anime path;
  upstream declares Apache-2.0.
- **Sakura-GalTransl-7B-v3.7** (`SakuraLLM/...`) — default translation model; upstream declares
  CC-BY-NC-SA-4.0 and explicitly prohibits commercial use.
- **Qwen3-ASR-1.7B** (`Qwen/...`) — optional ASR model; upstream declares Apache-2.0.
- **Sakura-14B-Qwen2.5-v1.0-GGUF** (`SakuraLLM/...`) — optional translation model; upstream
  declares CC-BY-NC-SA-4.0 and is distributed as a non-commercial package.
- **voice-gender-classifier** (`JaesungHuh/...`) — optional ECAPA speaker-colouring model;
  upstream declares MIT and warns that its training data may introduce demographic bias.
- **Sugoi-14B-Ultra-GGUF** (`sugoitoolkit/...`) — optional Japanese-to-English
  translation model; its model card declares Apache-2.0. Model redistribution remains separate
  from the program archive and requires retaining its upstream model card and license material.

Model archives are distributed separately from the program archive and must retain their
package-specific `licenses/models/` directory, containing the relevant upstream model cards,
license texts, and `MODEL_LICENSE_STATUS.txt`. These entries record upstream declarations and
are not legal advice.
