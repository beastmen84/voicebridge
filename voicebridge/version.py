from voicebridge.app_paths import external_base_dir, source_base_dir

APP_VERSION_FALLBACK = "1.0.2"
VERSION_FILENAME = "VERSION"


def app_version() -> str:
    for path in (external_base_dir() / VERSION_FILENAME, source_base_dir() / VERSION_FILENAME):
        try:
            version = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if version:
            return version
    return APP_VERSION_FALLBACK
