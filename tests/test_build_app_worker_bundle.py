import ast
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKER_SCRIPTS = (
    PROJECT_ROOT / "stt_worker.py",
    PROJECT_ROOT / "local_tts_worker.py",
    PROJECT_ROOT / "voice_modeling_worker.py",
    PROJECT_ROOT / "video_anomaly_worker.py",
)


def test_build_app_copies_worker_voicebridge_dependencies() -> None:
    required_modules = worker_voicebridge_module_dependencies(WORKER_SCRIPTS)
    copied_modules = build_app_worker_support_modules()

    assert required_modules <= copied_modules


def test_build_app_preserves_runtime_data_directories() -> None:
    preserve_names = build_app_preserve_names()

    assert {"voice_profiles", "modeling_exports", "voice_models", "logs"} <= preserve_names


def worker_voicebridge_module_dependencies(worker_paths: tuple[Path, ...]) -> set[str]:
    required_modules: set[str] = set()
    visited_paths: set[Path] = set()
    pending_paths = list(worker_paths)

    while pending_paths:
        path = pending_paths.pop(0)
        if path in visited_paths:
            continue
        visited_paths.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module_name in iter_voicebridge_module_imports(tree):
            module_path = PROJECT_ROOT / "voicebridge" / f"{module_name}.py"
            if not module_path.is_file():
                continue
            required_modules.add(module_name)
            if module_path not in visited_paths and module_path not in pending_paths:
                pending_paths.append(module_path)

    return required_modules


def iter_voicebridge_module_imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("voicebridge."):
            yield node.module.split(".")[1]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("voicebridge."):
                    yield alias.name.split(".")[1]


def build_app_worker_support_modules() -> set[str]:
    build_script = (PROJECT_ROOT / "build_app.ps1").read_text(encoding="utf-8")
    match = re.search(
        r"\$workerSupportModules\s*=\s*@\((?P<body>.*?)\)",
        build_script,
        flags=re.DOTALL,
    )
    assert match is not None
    return set(re.findall(r'"([a-zA-Z0-9_]+)"', match.group("body")))


def build_app_preserve_names() -> set[str]:
    build_script = (PROJECT_ROOT / "build_app.ps1").read_text(encoding="utf-8")
    match = re.search(r"\$preserveNames\s*=\s*@\((?P<body>.*?)\)", build_script)
    assert match is not None
    return set(re.findall(r'"([^"]+)"', match.group("body")))
