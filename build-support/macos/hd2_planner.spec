# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for the Apple-Silicon-only desktop bundle."""
from pathlib import Path
import importlib.metadata
import sys
import tkinter

import PyInstaller


repo_root = Path(SPECPATH).parents[1]
version = (repo_root / "VERSION").read_text(encoding="utf-8").strip()
python_license = Path(sys.base_prefix) / "lib" / "python3.14" / "LICENSE.txt"
tk_patch = str(tkinter.Tcl().eval("info patchlevel"))
tk_series = ".".join(tk_patch.split(".")[:2])
embedded_frameworks = Path(sys.base_prefix) / "Frameworks"
tcl_license = embedded_frameworks / "Tcl.framework" / "Versions" / tk_series / "Resources" / "license.terms"
tk_license = embedded_frameworks / "Tk.framework" / "Versions" / tk_series / "Resources" / "license.terms"
pyinstaller_distribution = importlib.metadata.distribution("pyinstaller")
pyinstaller_license_entry = next(
    entry for entry in pyinstaller_distribution.files if entry.name == "COPYING.txt"
)
pyinstaller_license = Path(pyinstaller_distribution.locate_file(pyinstaller_license_entry))

datas = [
    (str(repo_root / "catalog"), "catalog"),
    (str(repo_root / "community"), "community"),
    (str(repo_root / "docs"), "docs"),
    (str(repo_root / "onboarding"), "onboarding"),
    (str(repo_root / "planner"), "planner"),
    (str(repo_root / "schemas"), "schemas"),
    (str(repo_root / "VERSION"), "."),
    (str(repo_root / ".python-version"), "."),
    (str(repo_root / "LICENSE"), "."),
    (str(repo_root / "LICENSE_OR_ATTRIBUTION.md"), "."),
    (str(repo_root / "profiles" / "example_player.json"), "examples/profiles"),
    (
        str(repo_root / "profiles" / "loadouts" / "example_illuminate_general.json"),
        "examples/profiles/loadouts",
    ),
    (str(python_license), "licenses/python"),
    (str(tcl_license), "licenses/tcl"),
    (str(tk_license), "licenses/tk"),
    (str(pyinstaller_license), "licenses/pyinstaller"),
]
runtime_libraries = [
    (str(Path(sys.base_prefix) / "lib" / name), ".")
    for name in ("libcrypto.3.dylib", "libssl.3.dylib", "libzstd.1.dylib")
]

analysis = Analysis(
    [str(repo_root / "hd2_gui.py")],
    pathex=[str(repo_root)],
    binaries=runtime_libraries,
    datas=datas,
    hiddenimports=["_tkinter", "tkinter", "tkinter.ttk", "tkinter.simpledialog"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["test", "tests", "unittest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="HD2 Planner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HD2 Planner",
)

app = BUNDLE(
    collection,
    name="HD2 Planner.app",
    icon=None,
    bundle_identifier="com.oidevo.hd2-planner",
    version=version,
    info_plist={
        "CFBundleDisplayName": "HD2 Planner",
        "CFBundleName": "HD2 Planner",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": "11.0",
        "LSArchitecturePriority": ["arm64"],
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "HD2EmbeddedPythonVersion": "3.14.7",
        "HD2EmbeddedTkVersion": "9.0.4",
        "HD2PyInstallerVersion": "6.22.3",
    },
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
