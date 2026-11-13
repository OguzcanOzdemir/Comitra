# PyInstaller spec: one folder containing the GUI app ("Comitra") and a
# console helper ("comitra-cli"). On macOS the folder becomes Comitra.app.
# Build with:  pyinstaller --noconfirm --clean packaging/comitra.spec
# (packaging/build.py does this and creates the installers.)

import os
import sys

HERE = os.path.dirname(os.path.abspath(SPEC))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from comitra import __version__  # noqa: E402

ICONS = os.path.join(HERE, "build-icons")
if sys.platform == "win32":
    icon = os.path.join(ICONS, "comitra.ico")
elif sys.platform == "darwin":
    icon = os.path.join(ICONS, "comitra.icns")
else:
    icon = None
if icon and not os.path.isfile(icon):
    icon = None

EXCLUDES = [
    "tkinter", "unittest", "pydoc_data", "test",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
    "PySide6.QtBluetooth", "PySide6.QtNetworkAuth", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtWebSockets",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtXml", "PySide6.QtNetwork",
]

a = Analysis(
    [os.path.join(HERE, "launcher.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "comitra", "ui", "resources", "icon.png"), os.path.join("comitra", "ui", "resources"))],
    hiddenimports=["platformdirs"],
    excludes=EXCLUDES,
    noarchive=False,
)
# Qt plugins drag in Qt Quick/QML/PDF/virtual keyboard (~40 MB) that a
# widgets app never uses. Drop them, and all translations except TR/EN.
DROP = ("Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard", "QtQuick", "QtQml", "QtPdf",
        "QtVirtualKeyboard", "qtvirtualkeyboardplugin", "qpdf")


def _keep(entry):
    dest = entry[0].replace("\\", "/")
    name = dest.rsplit("/", 1)[-1]
    if any(d in name for d in DROP) or any(f"/{d}" in dest for d in ("QtQuick.framework", "QtQml.framework", "QtPdf.framework")):
        return False
    if "/translations/" in dest and dest.endswith(".qm") and not dest.endswith(("_tr.qm", "_en.qm")):
        return False
    return True


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]
pyz = PYZ(a.pure)

gui = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Comitra",
    console=False,
    icon=icon,
    upx=False,
)
cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="comitra-cli",
    console=True,
    icon=icon,
    upx=False,
)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="Comitra", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Comitra.app",
        icon=icon,
        bundle_identifier="io.github.comitra",
        version=__version__,
        info_plist={
            "CFBundleName": "Comitra",
            "CFBundleDisplayName": "Comitra",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSRequiresAquaSystemAppearance": False,
            "NSDesktopFolderUsageDescription": "Comitra searches git repositories in the folders you choose.",
            "NSDocumentsFolderUsageDescription": "Comitra searches git repositories in the folders you choose.",
            "NSDownloadsFolderUsageDescription": "Comitra searches git repositories in the folders you choose.",
            "NSRemovableVolumesUsageDescription": "Comitra searches git repositories in the folders you choose.",
            "NSNetworkVolumesUsageDescription": "Comitra searches git repositories in the folders you choose.",
        },
    )
