# Third-Party Notices

This project incorporates code adapted from third-party open-source projects.

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
  optional `--text-backend anime` text source.
- **Whisper-Vad-EncDec-ASMR-onnx** (`TransWithAI/...`) — WhisperSeg VAD, planned for the
  optional Stage 3 speech-segmentation backend.
