# Changelog

All notable changes should be documented here before public releases.

VoiceBridge currently uses manual release notes. The beta versions below are reconstructed milestones based on commit history; they are not guaranteed to match existing git tags.

## Unreleased

No unreleased changes.

## 1.0.1 - Word transcripts and STT details cleanup

- Added Word `.docx` output for offline transcripts.
- Suppressed the noisy optional TorchCodec audio-decoding warning from STT details.

## 1.0 - First stable local release

### Changed

- Added a root `VERSION` file and displayed `V. 1.0` in the app sidebar footer.
- Limited generated guided modeling prompts to 200 characters for XTTS-v2 training compatibility.
- Enforced the Training tab sequence so jobs move through `Prepare`, `Dry run` and `Start training` in order.
- Updated the recording reader so semicolons no longer force a new reading line.
- Added permanent dataset recording guidance for natural, clear audiobook-style reads.
- Suggested XTTS training defaults from dataset size and detected CUDA VRAM instead of using a fixed epoch/batch default.
- Disabled primary action styling until TTS, STT and Subtitles have the required input files selected.

### Fixed

- Preserved the real XTTS training error on Windows by avoiding locked trainer log cleanup.
- Blocked training preparation for exported datasets with transcript rows longer than the XTTS-v2 text limit.
- Avoided creating empty voice model output folders during preflight/config validation.
- Removed safely identifiable empty training output folders when deleting linked modeling profiles.
- Archived logs and pruned completed XTTS training checkpoint folders after the inference model is exported.
- Stopped automatically opening Explorer after dataset export and training config save.
- Preserved current modeling dataset export state when profile sync does not change the dataset.
- Warned before XTTS training when available CUDA VRAM appears low and improved CUDA out-of-memory guidance.

## 0.9b - Public-ready beta

### Added

- Added repository-level public documentation:
  - `SECURITY.md`
  - `CONTRIBUTING.md`
  - `CHANGELOG.md`
  - README CI badge and dashboard screenshot
- Added printable user manual in `Manual.html` and bundled it with the app.
- Added privacy/local-data documentation covering local processing, Edge TTS online behavior and model downloads.

### Changed

- Improved guided recording reader formatting so long modeling prompts use the same reading breaks as reference voice recording.
- Improved text verification scoring by normalizing common Italian number and half-hour variants before comparison.
- Updated app packaging to include public documentation and README screenshot assets.
- Preserved runtime data folders during rebuilds:
  - `voice_profiles`
  - `modeling_exports`
  - `voice_models`

### Fixed

- Released preview audio before keeping modeling clips to avoid Windows file locks.
- Avoided orphaned cancelled modeling recordings.
- Allowed selecting the microphone used for dataset recording.
- Added cancellation support for XTTS training asset downloads.

### Notes

- XTTS-v2 model, assets and generated output remain limited to non-commercial use under the Coqui Public Model License.

## 0.8b - Localization and runtime stability beta

### Added

- Added Italian UI localization with language selection.
- Added printable in-app manual access from the sidebar.

### Changed

- Improved high-DPI behavior for Full HD Windows displays.
- Improved Edge TTS offline handling and retry behavior when connectivity changes.
- Stabilized async job state transitions across long-running workflows.

### Fixed

- Fixed startup and runtime cases where Edge TTS availability could leave the UI in an inconsistent state.
- Fixed Full HD scaling behavior on laptops using 150% Windows scaling.
- Fixed modeling asset download cancellation behavior.

## 0.7b - Cleanup workflow hardening beta

### Added

- Added suspicious-frame detection for Video Cleanup using OpenCV.
- Added documentation for suspicious video frame detection.

### Changed

- Improved Video Cleanup frame review workflow for single-frame inspection.
- Improved black-frame and transition-frame handling.
- Stabilized audio cleanup processing and video frame counting.

### Fixed

- Prevented orphaned modeling datasets when voice profiles are deleted.
- Added explicit destructive-delete confirmation for voice profiles with linked modeling work.
- Fixed Linux CI runtime packages and kept smoke imports lightweight.

## 0.6b - Service-layer extraction beta

### Added

- Added reusable worker subprocess runner for `STATUS:` / `PROGRESS:` style jobs.
- Added reusable FFmpeg progress parsing helpers.
- Added architecture review notes for future FFmpeg job extraction.

### Changed

- Migrated these worker paths to the shared process runner:
  - Voice Modeling training
  - STT transcription/alignment worker
  - Local TTS worker
  - Local TTS model download
  - Whisper model download
  - Alignment model download
- Migrated these FFmpeg progress/log parsing paths to shared helpers:
  - Subtitles FFmpeg process
  - Audio Cleanup FFmpeg process
  - Video Cleanup repair FFmpeg process

### Notes

- These refactors were intentionally backend/service-layer only and preserved PySide6 UI behavior.

## 0.5b - Guided dataset verification beta

### Added

- Added guided modeling prompt generation.
- Expanded multilingual prompt corpus and variety checks.
- Added prevention of guided prompt reuse.
- Added Whisper-based text verification for guided dataset clips.
- Added recovery for interrupted modeling verifications.
- Added CI with pytest, ruff and lightweight import smoke tests.

### Changed

- Clarified modeling dataset export UX and quality guidance.
- Optimized modeling dataset verification refresh.
- Added schema versioning for app JSON files.
- Added per-kind schema versions for JSON files.
- Cleaned up legacy AppData config on startup.
- Refined subtitle burn-in style controls.

## 0.4b - Local voice modeling beta

### Added

- Added modeling dataset workflow.
- Added modeling dataset readiness summary and target progress.
- Added modeling dataset export.
- Added voice modeling configuration page.
- Added voice modeling preflight checks.
- Added DVAE download and voice training tab.
- Wired XTTS voice training worker.
- Connected trained voice models back into Local TTS.

### Changed

- Organized Local Voices into tabs and gated tabs by available data.
- Tightened Local Voices layout.
- Grouped Local TTS voice choices.
- Reorganized sidebar navigation groups and page badges.
- Switched project license to MPL-2.0.
- Avoided bundling duplicate model cache.

## 0.3b - Audio cleanup and timeline beta

### Added

- Added manual Audio Cleanup page.
- Added waveform selection and preview workflow.
- Added local multi-voice TTS blocks.
- Added TTS block timelines for Audio Cleanup.
- Added queued multi-change Audio Cleanup operations.

### Changed

- Refined Audio Cleanup startup, playback, seek and preview controls.
- Updated TTS timelines after Audio Cleanup edits.
- Clarified Audio Cleanup scope.

## 0.2b - Local TTS and voice profile beta

### Added

- Added selectable STT compute device.
- Added voice profile management.
- Added local TTS profile selection.
- Added Local TTS worker and license notices.
- Added embedded voice profile recorder.
- Added XTTS model predownload flow.
- Added Local TTS status tile.
- Added stable XTTS inference preset and local TTS inference presets.
- Added downloadable STT model setup.

### Changed

- Improved local TTS text cleanup and dialog behavior.
- Split Local TTS text into XTTS chunks.
- Refined chunk merging and punctuation handling for XTTS.
- Improved voice profile recording cleanup, microphone handling and reading script readability.
- Added auto-scroll and smooth scroll for voice recording scripts.

### Fixed

- Fixed TTS output moves across drives.
- Removed legacy STT runtime support.
- Hid XTTS download when the model is already ready.
- Deleted recorded audio when deleting voice profiles.

## 0.1b - Initial desktop beta

### Added

- Initial VoiceBridge PySide6 desktop baseline.
- Modularized the app into `voicebridge/` package modules.
- Added shared constants, UI helpers, stylesheet module and page builders.
- Extracted workflow mixins for:
  - Text to Speech
  - Transcription
  - Subtitles
  - Video Cleanup
  - Home page
- Added pytest coverage for core helpers.

### Notes

- This beta established the desktop app structure used by later workflow additions.
