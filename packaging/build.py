"""Build installers and portable packages for the current platform.

    python packaging/build.py            # everything available on this OS
    python packaging/build.py --skip-installer

Output goes to ``dist/release``:

* Windows: ``Comitra-<ver>-windows-x64-setup.exe`` (Inno Setup, per-user, no
  admin rights) and ``Comitra-<ver>-windows-x64-portable.zip``
* macOS:   ``Comitra-<ver>-macos-<arch>.dmg`` and ``…-portable.zip``
* Linux:   ``Comitra-<ver>-linux-x86_64.AppImage`` and ``…-portable.tar.gz``

Portable packages contain ``comitra-portable.txt`` next to the program, which
makes Comitra keep its settings and database in ``comitra-data`` beside it.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from comitra import __version__  # noqa: E402

DIST = os.path.join(ROOT, "dist")
OUT = os.path.join(DIST, "release")
PORTABLE_NOTE = (
    "Comitra portable mode\n"
    "=====================\n"
    "Because this file exists, Comitra stores its settings and database in the\n"
    "'comitra-data' folder next to the program instead of your user profile.\n"
    "Delete this file to use the normal per-user locations.\n"
)
APPIMAGETOOL_URL = "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def arch() -> str:
    m = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(m, m)


def build_pyinstaller() -> None:
    run([sys.executable, os.path.join(HERE, "make_icons.py")])
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", DIST, "--workpath", os.path.join(ROOT, "build", "pyinstaller"),
         os.path.join(HERE, "comitra.spec")])


def zip_dir(src: str, dest_zip: str, arc_root: str, extra: dict[str, str] | None = None) -> None:
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, dirs, files in os.walk(src):
            for name in dirs + files:
                full = os.path.join(base, name)
                rel = os.path.relpath(full, src)
                arc = os.path.join(arc_root, rel)
                if os.path.islink(full):
                    info = zipfile.ZipInfo(arc)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    z.writestr(info, os.readlink(full))
                elif os.path.isfile(full):
                    z.write(full, arc)
        for arc, content in (extra or {}).items():
            z.writestr(os.path.join(arc_root, arc), content)
    print("wrote", dest_zip)


# -- Windows ---------------------------------------------------------------------

def find_iscc() -> str | None:
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        cand = os.path.join(base, "Inno Setup 6", "ISCC.exe")
        if base and os.path.isfile(cand):
            return cand
    return None


def package_windows(skip_installer: bool) -> None:
    app_dir = os.path.join(DIST, "Comitra")
    name = f"Comitra-{__version__}-windows-{arch()}"
    zip_dir(app_dir, os.path.join(OUT, f"{name}-portable.zip"), "Comitra",
            {"comitra-portable.txt": PORTABLE_NOTE})
    if skip_installer:
        return
    iscc = find_iscc()
    if not iscc:
        print("Inno Setup (ISCC.exe) not found – skipping installer. Install it from https://jrsoftware.org/isinfo.php")
        return
    run([iscc, f"/DAppVersion={__version__}", f"/DSourceDir={app_dir}", f"/DOutputDir={OUT}",
         f"/DOutputName={name}-setup", f"/DIconFile={os.path.join(HERE, 'build-icons', 'comitra.ico')}",
         os.path.join(HERE, "windows", "comitra.iss")])


# -- macOS -----------------------------------------------------------------------

def package_macos(skip_installer: bool) -> None:
    app = os.path.join(DIST, "Comitra.app")
    name = f"Comitra-{__version__}-macos-{arch()}"
    # Ad-hoc signature so Apple Silicon accepts the bundle (no developer ID needed).
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", app], check=False)
    stage = os.path.join(DIST, "portable-mac")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    run(["ditto", app, os.path.join(stage, "Comitra.app")])
    with open(os.path.join(stage, "comitra-portable.txt"), "w") as fh:
        fh.write(PORTABLE_NOTE)
    portable_zip = os.path.join(OUT, f"{name}-portable.zip")
    if os.path.exists(portable_zip):
        os.remove(portable_zip)
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", stage, portable_zip])
    if skip_installer:
        return
    dmg_src = os.path.join(DIST, "dmg")
    shutil.rmtree(dmg_src, ignore_errors=True)
    os.makedirs(dmg_src)
    run(["ditto", app, os.path.join(dmg_src, "Comitra.app")])
    os.symlink("/Applications", os.path.join(dmg_src, "Applications"))
    dmg = os.path.join(OUT, f"{name}.dmg")
    if os.path.exists(dmg):
        os.remove(dmg)
    run(["hdiutil", "create", "-volname", f"Comitra {__version__}", "-srcfolder", dmg_src,
         "-ov", "-format", "UDZO", dmg])


# -- Linux -----------------------------------------------------------------------

def _appimagetool() -> str | None:
    found = shutil.which("appimagetool")
    if found:
        return found
    dest = os.path.join(ROOT, "build", "appimagetool-x86_64.AppImage")
    if not os.path.isfile(dest):
        try:
            print("downloading appimagetool…")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            urllib.request.urlretrieve(APPIMAGETOOL_URL, dest)
        except Exception as exc:  # pragma: no cover - network dependent
            print("could not download appimagetool:", exc)
            return None
    os.chmod(dest, 0o755)
    return dest


def package_linux(skip_installer: bool) -> None:
    app_dir = os.path.join(DIST, "Comitra")
    name = f"Comitra-{__version__}-linux-{platform.machine()}"
    lin = os.path.join(HERE, "linux")
    # portable tar.gz (+ optional desktop integration script)
    tgz = os.path.join(OUT, f"{name}-portable.tar.gz")
    with tarfile.open(tgz, "w:gz") as t:
        t.add(app_dir, arcname="Comitra")
        for fname in ("install.sh", "comitra.desktop"):
            t.add(os.path.join(lin, fname), arcname=f"Comitra/{fname}")
        t.add(os.path.join(ROOT, "comitra", "ui", "resources", "icon.png"), arcname="Comitra/comitra.png")
        info = tarfile.TarInfo("Comitra/comitra-portable.txt")
        data = PORTABLE_NOTE.encode()
        info.size = len(data)
        info.mode = 0o644
        import io

        t.addfile(info, io.BytesIO(data))
    print("wrote", tgz)
    if skip_installer:
        return
    tool = _appimagetool()
    if not tool:
        print("appimagetool not available – skipping AppImage")
        return
    appdir = os.path.join(DIST, "Comitra.AppDir")
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(app_dir, os.path.join(appdir, "usr", "lib", "comitra"), symlinks=True)
    shutil.copy(os.path.join(lin, "AppRun"), os.path.join(appdir, "AppRun"))
    os.chmod(os.path.join(appdir, "AppRun"), 0o755)
    shutil.copy(os.path.join(lin, "comitra.desktop"), os.path.join(appdir, "comitra.desktop"))
    shutil.copy(os.path.join(ROOT, "comitra", "ui", "resources", "icon.png"), os.path.join(appdir, "comitra.png"))
    icons = os.path.join(appdir, "usr", "share", "icons", "hicolor", "512x512", "apps")
    os.makedirs(icons)
    shutil.copy(os.path.join(ROOT, "comitra", "ui", "resources", "icon.png"), os.path.join(icons, "comitra.png"))
    out = os.path.join(OUT, f"{name}.AppImage")
    env = dict(os.environ, ARCH=platform.machine(), APPIMAGE_EXTRACT_AND_RUN="1")
    run([tool, "--no-appstream", appdir, out], env=env)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--skip-installer", action="store_true", help="only build the portable package")
    p.add_argument("--skip-pyinstaller", action="store_true", help="reuse dist/Comitra from a previous run")
    args = p.parse_args()
    os.makedirs(OUT, exist_ok=True)
    if not args.skip_pyinstaller:
        build_pyinstaller()
    if sys.platform == "win32":
        package_windows(args.skip_installer)
    elif sys.platform == "darwin":
        package_macos(args.skip_installer)
    else:
        package_linux(args.skip_installer)
    print("\nRelease files:")
    for f in sorted(os.listdir(OUT)):
        print("  ", os.path.join(OUT, f))


if __name__ == "__main__":
    main()
