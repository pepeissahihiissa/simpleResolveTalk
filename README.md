# SimpleResolveTalk

日本語PSD（レイヤー構造から表情を合成）を読み込み、口パク・まばたき用の
PNGシーケンスを生成し、DaVinci Resolve に配置するためのツール一式です。

- `simpleTalkGui.py` : デスクトップGUI（PSD読込 → 表情合成 → シーケンス出力 → Resolve配置）
- `character_lip_sync.py` : Resolve用のスクリプト（タイムライン上のクリップを口パク/まばたき化）

## 構成

| ファイル | 説明 |
| --- | --- |
| `simpleTalkGui.py` | GUI本体（tkinter + psd-tools + Pillow） |
| `character_lip_sync.py` | Resolve配置スクリプト（GUIがResolveのScriptsフォルダへ自動配備） |
| `config.default.json` | 初期設定テンプレート（初回起動時に `config.json` を自動生成） |
| `simpleResolveTalk.spec` | PyInstaller の onefile 定義 |

> `config.json` は実行時のユーザーデータ（作成キャラ・設定）を保持するため、
> リポジトリには含めません。公開用リポジトリでは `.gitignore` により除外されます。

## 必要な環境（開発側）

- Windows + Python 3.10
- 依存パッケージは `requirements.txt` を参照

```
pip install -r requirements.txt
```

GUIを起動:

```
python simpleTalkGui.py
```

## テスト

```
python -m pytest tests -q
```

## exe のビルド（onefile）

```
pip install pyinstaller
python -m PyInstaller simpleResolveTalk.spec --noconfirm
```

`dist\simpleResolveTalk.exe` が生成されます
（`character_lip_sync.py`・`config.default.json`・ガイド用スクリーンショット
`step1.png`〜`step4.png` を同梱。初回起動時に `config.json` を生成し、
Resolve側スクリプトをexe横へ展開します）。
重いライブラリ（torch / scipy / skimage / cv2 等）を `excludes` で除外しているため約25MBです。

## DaVinci Resolve での使い方

前提: **DaVinci Resolve 20 Free / Studio**。以下のワークフローは
Resolveの **Workspace → Scripts** メニューからスクリプトを呼び出す方式です。

### 1. Resolveにスクリプトを認識させる

GUIは外部スクリプトを複数の候補パスから検出・自動コピーします。

- `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility\`（推奨・管理者権限が必要な場合あり）
- `%APPDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility\`
- `C:\Program Files\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility\`

`character_lip_sync.py` が上記の場所に置かれると、
Resolveの **Workspace → Scripts → Utility → character_lip_sync** で実行できます。

### 2. 外部スクリプト設定（重要）

Resolveは外部Pythonスクリプト用に別のPythonを要求する場合があります。
GUI起動時に対象バージョンを選択するか、システムのPython（psd-tools/Pillow入り）を指定してください。

### 3. 実行フロー

1. Resolveでプロジェクトとタイムラインを開きます（クリップは1トラック上で連続配置）。
2. GUIでPSDを読み込み、normal / blink / talk の各レイヤーを設定し、PNGシーケンスを出力します。
3. GUIの「Resolve配置」で `character_lip_sync` を実行します。
   クリップ名とフォルダ名から対象キャラ・口パク/まばたき種別を自動判定します。

### クリップ命名規則

Resolve上でクリップ名にフォルダ名（キャラ名）とモーション種別を保持しておくと
自動判定されます。例:

```
もち子_2_1_normal_[0000-0009].png   → 10フレームの通常（静止）ループ
もち子_2_1_talk_a_30               → 口パクA（30f）
もち子_2_1_blink_10                → まばたき（10f）
```

`GetClipProperty("File Path")` から元フォルダのフルパスを取得するため、
クリップ名が同一でも異なるフォルダ（キャラ）のクリップを正しく区別できます。

## ライセンス

[MIT License](LICENSE)

Copyright (c) 2026 Pepeissa Hihiissa

## 同梱ライブラリのライセンス

本ツールが利用する主なライブラリはすべて許容的なライセンスです（独自OK）。

| ライブラリ | ライセンス |
| --- | --- |
| psd-tools | MIT |
| Pillow | HPND（BSD系） |
| numpy | BSD-3-Clause |
| attrs | MIT |
| packaging | BSD-2-Clause / Apache-2.0 |
| Python / tkinter | PSF-2.0 |
| PyInstaller（ビルド用） | GPL-2.0-or-later + 特別例外（ビルドしたアプリの配布は任意ライセンス可能） |
