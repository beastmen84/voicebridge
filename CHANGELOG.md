# Changelog

All notable changes should be documented here before public releases.

This project currently uses manual release notes.

## Unreleased

### Added

- Printable user manual in `Manual.html`.
- Local voice modeling dataset recording, text verification and export readiness workflow.
- Video Cleanup frame review with black-frame detection and suspicious-frame detection.
- Shared subprocess job helpers for worker-style tasks.
- Shared FFmpeg progress parsing helpers.
- CI workflow for ruff, pytest and lightweight import smoke tests.

### Changed

- Build script preserves runtime data folders during app rebuilds:
  - `voice_profiles`
  - `modeling_exports`
  - `voice_models`
- Text verification normalizes common Italian number and half-hour variants before scoring.
- Guided recording reader formats long prompts with reading breaks.

### Security / Privacy

- Documented local data behavior and Edge TTS online behavior in `README.md`.
- Added `SECURITY.md`.

### Notes

- XTTS-v2 model, assets and generated output are limited to non-commercial use under the Coqui Public Model License.
