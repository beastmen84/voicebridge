# Contributing

Contributions should keep VoiceBridge practical, local-first and safe for desktop use.

## Basic Workflow

1. Create a focused branch.
2. Keep changes small and reviewable.
3. Do not commit generated files, local data, models, virtual environments or build output.
4. Run checks before opening a pull request.

## Development Setup

Main app environment:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest ruff pyinstaller
```

Optional ML runtime:

```powershell
py -3.13 -m venv .venv-ml
.\.venv-ml\Scripts\python.exe -m pip install -r requirements-stt.txt
.\.venv-ml\Scripts\python.exe -m pip install -r requirements-local-tts.txt
```

## Checks

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

## What Not To Commit

Do not commit:

- `dist/`
- `build/`
- `.venv/`
- `.venv-ml/`
- `models/`
- `voice_profiles/`
- `modeling_exports/`
- `voice_models/`
- personal audio/video samples
- generated datasets or trained voice outputs

## Product Constraints

- Do not require CUDA for core checks.
- Do not download models in CI.
- Do not add online services without clearly documenting privacy behavior.
- Keep PySide6 UI behavior stable unless the change explicitly targets UI behavior.
- Preserve the non-commercial XTTS-v2 limitation in documentation and UX when relevant.
