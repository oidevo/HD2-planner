"""Release packaging for the source ZIP and Apple Silicon macOS app."""
from __future__ import annotations

import importlib.metadata
import os
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .constants import APP_VERSION, ROOT


INCLUDE_FILES = [
    "hd2.py",
    "hd2_gui.py",
    "VERSION",
    ".python-version",
    "README.md",
    "LICENSE",
    "LICENSE_OR_ATTRIBUTION.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "requirements-build-macos.txt",
]
INCLUDE_DIRS = [
    "hd2lib",
    "catalog",
    "community",
    "docs",
    "planner",
    "importer",
    "onboarding",
    "schemas",
    "tests",
    "build-support",
]

MACOS_BUNDLE_NAME = "HD2 Planner.app"
MACOS_BUNDLE_IDENTIFIER = "com.oidevo.hd2-planner"
MACOS_ARCHITECTURE = "arm64"
MACOS_MINIMUM_SYSTEM_VERSION = "11.0"
EMBEDDED_PYTHON_VERSION = "3.14.7"
EMBEDDED_TK_VERSION = "9.0.4"
PYINSTALLER_VERSION = "6.22.3"

_PRIVATE_DIRECTORY_NAMES = {
    ".build",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "backups",
    "caches",
    "generated",
    "logs",
    "migrations",
    "profiles",
    "raw",
    "staging",
    "tests",
    "tmp",
}
_PRIVATE_FILE_NAMES = {".DS_Store", "settings.json"}
_MACHINE_SPECIFIC_PATHS = (
    b"/Users/",
    b"/opt/homebrew/",
    b"/usr/local/Homebrew/",
    b"/usr/local/Cellar/",
    b"/usr/local/opt/",
    b"/private/tmp/",
    b"/var/folders/",
    b"/Desktop/",
    b"/usr/bin/python3",
)
_USER_HOME_PREFIX = re.compile(rb"/Users/[^/\x00]+/")


@dataclass(frozen=True)
class MacOSBuildRuntime:
    python: str
    tk: str
    pyinstaller: str
    architecture: str


def _bundle_version(root: Path) -> str:
    version_file = root / "VERSION"
    if not version_file.exists():
        raise FileNotFoundError(f"Cannot build a macOS app without {version_file}")
    return version_file.read_text(encoding="utf-8").strip()


def _release_copy_ignore(_: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in {"__pycache__", "raw", "staging", ".build", "build"}:
            ignored.add(name)
        elif name.endswith((".pyc", ".pyo", ".log", "~")) or name == ".DS_Store":
            ignored.add(name)
    return ignored


def build_package(output_directory: Path, root: Path = ROOT) -> Path:
    """Build the existing offline source ZIP without personal/runtime data."""
    output_directory.mkdir(parents=True, exist_ok=True)
    package_name = f"helldivers-planner-{APP_VERSION}"
    destination = output_directory / f"{package_name}.zip"
    with tempfile.TemporaryDirectory(prefix="hd2-package-") as temporary:
        stage = Path(temporary) / package_name
        stage.mkdir()
        for filename in INCLUDE_FILES:
            source = root / filename
            if source.exists():
                shutil.copy2(source, stage / filename)
        for dirname in INCLUDE_DIRS:
            source = root / dirname
            if source.exists():
                shutil.copytree(source, stage / dirname, ignore=_release_copy_ignore)

        profiles = stage / "examples" / "profiles"
        profiles.mkdir(parents=True)
        example = root / "profiles" / "example_player.json"
        if example.exists():
            shutil.copy2(example, profiles / example.name)
        loadout = root / "profiles" / "loadouts" / "example_illuminate_general.json"
        if loadout.exists():
            (profiles / "loadouts").mkdir()
            shutil.copy2(loadout, profiles / "loadouts" / loadout.name)
        (stage / "generated").mkdir()

        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(stage.parent))
    return destination


def selected_macos_build_runtime() -> MacOSBuildRuntime:
    """Validate and describe the exact interpreter used for the frozen build."""
    try:
        import _tkinter
        import tkinter
    except ImportError as exc:
        raise RuntimeError(
            "The macOS app build requires the matching Tk-enabled Python 3.14 "
            "interpreter; both tkinter and _tkinter must import successfully."
        ) from exc

    try:
        pyinstaller = importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            f"PyInstaller {PYINSTALLER_VERSION} is required as a build-only dependency. "
            "Create/activate a Python 3.14 build virtual environment and install "
            "requirements-build-macos.txt."
        ) from exc

    runtime = MacOSBuildRuntime(
        python=platform.python_version(),
        tk=str(tkinter.Tcl().eval("info patchlevel")),
        pyinstaller=pyinstaller,
        architecture=platform.machine(),
    )
    expected = MacOSBuildRuntime(
        python=EMBEDDED_PYTHON_VERSION,
        tk=EMBEDDED_TK_VERSION,
        pyinstaller=PYINSTALLER_VERSION,
        architecture=MACOS_ARCHITECTURE,
    )
    if sys.platform != "darwin":
        raise RuntimeError("HD2 Planner.app can only be built on Apple Silicon macOS")
    if "homebrew" in str(Path(sys.base_prefix)).casefold():
        raise RuntimeError(
            "The final app must be built with the official Python.org 3.14.7 Tk-enabled runtime; "
            "Homebrew runtimes contain non-relocatable Homebrew build-prefix references."
        )
    if runtime != expected:
        raise RuntimeError(f"Unsupported macOS build runtime: {runtime!r}; expected {expected!r}")
    return runtime


def _pyinstaller_spec(root: Path) -> Path:
    spec = root / "build-support" / "macos" / "hd2_planner.spec"
    if not spec.is_file():
        raise FileNotFoundError(f"Missing PyInstaller specification: {spec}")
    return spec


def build_macos_app(output_directory: Path, root: Path = ROOT) -> Path:
    """Build a windowed, self-contained, unsigned Apple Silicon app bundle."""
    selected_macos_build_runtime()
    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / MACOS_BUNDLE_NAME
    spec = _pyinstaller_spec(root)

    with tempfile.TemporaryDirectory(prefix="hd2-pyinstaller-") as temporary:
        temporary_path = Path(temporary)
        dist_path = temporary_path / "dist"
        work_path = temporary_path / "work"
        environment = os.environ.copy()
        environment["MACOSX_DEPLOYMENT_TARGET"] = MACOS_MINIMUM_SYSTEM_VERSION
        environment["PYTHONHASHSEED"] = "0"
        environment["PYINSTALLER_CONFIG_DIR"] = str(temporary_path / "cache")
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist_path),
            "--workpath",
            str(work_path),
            str(spec),
        ]
        subprocess.run(command, cwd=root, env=environment, check=True)
        built = dist_path / MACOS_BUNDLE_NAME
        if not built.is_dir():
            raise RuntimeError(f"PyInstaller did not create {built}")
        _scrub_upstream_macos_build_paths(built)
        errors = macos_bundle_errors(built, expected_version=_bundle_version(root))
        if errors:
            raise RuntimeError("Invalid macOS application bundle:\n- " + "\n- ".join(errors))
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(built), str(destination))
    return destination


def _scrub_upstream_macos_build_paths(bundle: Path) -> None:
    """Remove compiler host home prefixes embedded in upstream runtime binaries."""
    changed = False

    def neutral_prefix(match: re.Match[bytes]) -> bytes:
        original = match.group()
        replacement = b"/Src/" + (b"_" * (len(original) - len(b"/Src//"))) + b"/"
        if len(replacement) != len(original):
            raise AssertionError("machine-path replacement must retain the Mach-O byte length")
        return replacement

    for path in bundle.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        payload = path.read_bytes()
        scrubbed = _USER_HOME_PREFIX.sub(neutral_prefix, payload)
        if scrubbed == payload:
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        path.write_bytes(scrubbed)
        path.chmod(mode)
        changed = True

    if changed:
        # arm64 Mach-O files require a valid load-time signature. This remains
        # an ad-hoc signature: no Developer ID identity or notarization is used.
        subprocess.run(
            ["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(bundle)],
            check=True,
        )


def _zip_info(path: Path, arcname: str) -> zipfile.ZipInfo:
    metadata = path.lstat()
    name = arcname + ("/" if stat.S_ISDIR(metadata.st_mode) else "")
    info = zipfile.ZipInfo(name, time.localtime(metadata.st_mtime)[:6])
    info.create_system = 3
    info.external_attr = (metadata.st_mode & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def build_macos_app_archive(bundle: Path, output_directory: Path, root: Path = ROOT) -> Path:
    """ZIP the app while retaining executable modes and framework symlinks."""
    destination = output_directory / f"hd2-planner-{_bundle_version(root)}-macos-arm64.zip"
    with zipfile.ZipFile(destination, "w") as archive:
        paths = [bundle, *sorted(bundle.rglob("*"))]
        for path in paths:
            relative = str(path.relative_to(bundle.parent))
            info = _zip_info(path, relative)
            if path.is_symlink():
                archive.writestr(info, os.readlink(path).encode("utf-8"))
            elif path.is_dir():
                archive.writestr(info, b"")
            else:
                with path.open("rb") as source, archive.open(info, "w") as target:
                    shutil.copyfileobj(source, target)
    return destination


def build_macos_app_package(output_directory: Path, root: Path = ROOT) -> tuple[Path, Path]:
    """Build the embedded ``.app`` and Apple-Silicon-specific ZIP archive."""
    bundle = build_macos_app(output_directory, root)
    return bundle, build_macos_app_archive(bundle, output_directory, root)


def private_payload_violations(root: Path) -> list[str]:
    """Return private/runtime paths that must not ship in release artifacts."""
    violations: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        parts = tuple(part.casefold() for part in relative.parts)
        has_private_directory = any(
            part in _PRIVATE_DIRECTORY_NAMES
            and not (part == "profiles" and index > 0 and parts[index - 1] == "examples")
            for index, part in enumerate(parts)
        )
        if has_private_directory:
            violations.append(str(relative))
        elif path.name in _PRIVATE_FILE_NAMES or path.name.endswith((".pyc", ".pyo", ".log", "~")):
            violations.append(str(relative))
    return sorted(set(violations))


def _first_matching(bundle: Path, predicate: object) -> Path | None:
    for path in bundle.rglob("*"):
        if callable(predicate) and predicate(path):
            return path
    return None


def macos_binary_dependency_violations(bundle: Path) -> list[str]:
    """Find non-system absolute dependencies or non-arm64 Mach-O payloads."""
    if sys.platform != "darwin":
        return []
    violations: list[str] = []
    for path in bundle.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        kind = subprocess.run(
            ["/usr/bin/file", "-b", str(path)], text=True, capture_output=True, check=False
        ).stdout
        if "Mach-O" not in kind:
            continue
        relative = path.relative_to(bundle)
        architectures = subprocess.run(
            ["/usr/bin/lipo", "-archs", str(path)], text=True, capture_output=True, check=False
        ).stdout.strip().split()
        if architectures != [MACOS_ARCHITECTURE]:
            violations.append(f"{relative}: architectures are {' '.join(architectures) or 'unknown'}")
        dependencies = subprocess.run(
            ["/usr/bin/otool", "-L", str(path)], text=True, capture_output=True, check=False
        ).stdout
        for line in dependencies.splitlines()[1:]:
            dependency = line.strip().split(" (", 1)[0]
            if dependency.startswith(("/opt/homebrew/", "/usr/local/", "/Users/")):
                violations.append(f"{relative}: external dependency {dependency}")
            if dependency == "/usr/bin/python3":
                violations.append(f"{relative}: system Python dependency {dependency}")
    return sorted(set(violations))


def machine_specific_reference_violations(bundle: Path) -> list[str]:
    """Find local build paths or external-interpreter references in payload bytes."""
    violations: list[str] = []
    for path in bundle.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        payload = path.read_bytes()
        for fragment in _MACHINE_SPECIFIC_PATHS:
            if fragment in payload:
                violations.append(f"{path.relative_to(bundle)}: contains {fragment.decode('ascii')}")
    return sorted(set(violations))


def macos_bundle_errors(bundle: Path, *, expected_version: str = APP_VERSION) -> list[str]:
    """Statically validate final bundle metadata, runtime, resources, and privacy."""
    errors: list[str] = []
    plist_path = bundle / "Contents" / "Info.plist"
    executable = bundle / "Contents" / "MacOS" / "HD2 Planner"
    if not plist_path.is_file():
        return ["Contents/Info.plist is missing"]
    with plist_path.open("rb") as stream:
        info = plistlib.load(stream)
    expected_metadata = {
        "CFBundleDisplayName": "HD2 Planner",
        "CFBundleIdentifier": MACOS_BUNDLE_IDENTIFIER,
        "CFBundleShortVersionString": expected_version,
        "CFBundleVersion": expected_version,
        "LSMinimumSystemVersion": MACOS_MINIMUM_SYSTEM_VERSION,
        "HD2EmbeddedPythonVersion": EMBEDDED_PYTHON_VERSION,
        "HD2EmbeddedTkVersion": EMBEDDED_TK_VERSION,
        "HD2PyInstallerVersion": PYINSTALLER_VERSION,
    }
    for key, expected in expected_metadata.items():
        if info.get(key) != expected:
            errors.append(f"{key} is {info.get(key)!r}; expected {expected!r}")
    if info.get("LSArchitecturePriority") != [MACOS_ARCHITECTURE]:
        errors.append("LSArchitecturePriority must contain only arm64")
    if not executable.is_file() or not os.access(executable, os.X_OK):
        errors.append("windowed bundle executable is missing or not executable")
    elif sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/lipo", "-archs", str(executable)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode or result.stdout.strip() != MACOS_ARCHITECTURE:
            errors.append(f"bundle executable architecture is {result.stdout.strip() or result.stderr.strip()!r}")

    required_exact = [
        "catalog/catalog_manifest.json",
        "schemas/profile.schema.json",
        "planner/rules.json",
        "onboarding/LOCAL_SETUP.md",
        "VERSION",
        "LICENSE",
        "LICENSE_OR_ATTRIBUTION.md",
        "examples/profiles/example_player.json",
    ]
    bundle_files = {str(path.relative_to(bundle)) for path in bundle.rglob("*") if path.is_file()}
    for relative in required_exact:
        if not any(name.endswith("/" + relative) for name in bundle_files):
            errors.append(f"immutable resource is missing: {relative}")
    if not _first_matching(bundle, lambda path: path.name == "Python" and "Python.framework" in path.parts):
        errors.append("embedded Python.framework runtime is missing")
    if not _first_matching(bundle, lambda path: path.name.startswith("_tkinter") and path.suffix == ".so"):
        errors.append("embedded _tkinter extension is missing")
    if not _first_matching(
        bundle,
        lambda path: (path.name.startswith("libtcl9") and path.suffix == ".dylib")
        or path.name == "Tcl",
    ):
        errors.append("embedded Tcl 9 library is missing")
    if not _first_matching(
        bundle, lambda path: path.name == "init.tcl" and any(part in {"_tcl_data", "tcl9.0"} for part in path.parts)
    ):
        errors.append("embedded Tcl script resources are missing")
    if not _first_matching(bundle, lambda path: path.name == "LICENSE.txt" and "python" in path.parts):
        errors.append("embedded Python license is missing")
    if not _first_matching(bundle, lambda path: path.name == "license.terms" and "tcl" in path.parts):
        errors.append("embedded Tcl license is missing")
    if not _first_matching(bundle, lambda path: path.name == "license.terms" and "tk" in path.parts):
        errors.append("embedded Tk license is missing")
    if not _first_matching(bundle, lambda path: path.name == "COPYING.txt" and "pyinstaller" in path.parts):
        errors.append("PyInstaller bootloader license is missing")
    errors.extend(f"private/runtime payload included: {item}" for item in private_payload_violations(bundle))
    errors.extend(macos_binary_dependency_violations(bundle))
    errors.extend(machine_specific_reference_violations(bundle))
    return errors
