# -*- mode: python ; coding: utf-8 -*-
# PyInstaller ビルド定義（onefile・GUIアプリ）
# ビルド:  pyinstaller SimpleTalkLipSync.spec --noconfirm
# 出力:   dist/SimpleTalkLipSync.exe
# 内包:   character_lip_sync.py（Resolveへ自動コピー）, config.default.json（初回設定）

a = Analysis(
    ["simpleTalkGui.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("character_lip_sync.py", "."),
        ("config.default.json", "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "torchvision",
        "torchaudio",
        "torchgen",
        "torchmetrics",
        "scipy",
        "skimage",
        "cv2",
        "matplotlib",
        "pytest",
        "twisted",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SimpleTalkLipSync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)