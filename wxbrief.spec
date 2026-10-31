# PyInstaller spec: one-file binary of wxbrief. Build with scripts/build_exe.ps1 (Windows) or
# `python -m PyInstaller wxbrief.spec` (any OS); the binary lands in dist/.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("wxbrief/ui/app.tcss", "wxbrief/ui"),
    ("wxbrief/data/stations.json.gz", "wxbrief/data"),
    ("wxbrief/data/demo/*.txt", "wxbrief/data/demo"),
    ("wxbrief/i18n/locales/*.toml", "wxbrief/i18n/locales"),
]
datas += collect_data_files("textual")  # Textual's own CSS and widget files
datas += collect_data_files("tzdata")  # zone files for zoneinfo (Windows has no system copy)

a = Analysis(
    ["wxbrief/__main__.py"],
    pathex=["."],
    datas=datas,
    # Textual and the wxbrief screens import some modules by name at run time.
    hiddenimports=collect_submodules("wxbrief") + collect_submodules("textual.widgets"),
    excludes=["tkinter", "pytest", "mypy", "timezonefinder"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="wxbrief",
    console=True,
    upx=False,
)
