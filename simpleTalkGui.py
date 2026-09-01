import os
import sys
import json
import random
import shutil
import time
import hashlib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
from psd_tools import PSDImage

CONFIG_FILE = "config.json"
# PSDレイヤー名のデコードに使う文字コード。
# 日本製PSD（Shift-JIS/CP932）はデフォルト(macroman)で化けるためcp932に設定。
_PSD_ENCODING = "cp932"
LOG_FILE = "simple_talk_gui.log"
RESOLVE_SCRIPT_NAME = "character_lip_sync.py"
ORIGINALS_DIR_NAME = "originals"

# ResolveのWorkspace→Scriptsに表示させるスクリプト置き場の候補。
# 環境によってProgramData/AppDataのどちらかにあるため、起動時に存在する場所を探す。
RESOLVE_SCRIPT_DIR_CANDIDATES = [
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility",
    r"%APPDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility",
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility",
]


def _app_dir():
    """設定・出力・ログなどの基準ディレクトリ。

    - 開発時（.py実行）: スクリプト本体のあるフォルダ
    - exe実行時: exe本体のあるフォルダ
    cwd（起動時のカレントディレクトリ）に依存しないよう固定する。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _config_path():
    return os.path.join(_app_dir(), CONFIG_FILE)


def _log_path():
    return os.path.join(_app_dir(), LOG_FILE)


def _log(message):
    """ログをコンソールとファイルの両方に出力する"""
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except Exception:
        pass


def _find_resolve_script_dir():
    """ResolveのScripts/Utilityディレクトリを探す。無ければ既定値を返す。"""
    expand = os.path.expandvars
    for cand in RESOLVE_SCRIPT_DIR_CANDIDATES:
        p = expand(cand)
        if os.path.isdir(p):
            return p
    return expand(RESOLVE_SCRIPT_DIR_CANDIDATES[0])

# 生成する状態フォルダ定義
#   (state, frames, 説明) - talk_a/talk_b のみ可変ブロック用に交互パターン
#   フォルダ名: {chara_id}_{video_track}_{audio_track}_{state}_{frames}
#   blink は常に10fでしか配置されないため、10fのみ生成する（30f/60fは生成しない）
FOLDER_DEFS = [
    {"state": "normal", "frames": 10},
    {"state": "blink",  "frames": 10},
    {"state": "talk",   "frames": 10},
    {"state": "normal", "frames": 30},
    {"state": "talk_a", "frames": 30},
    {"state": "talk_b", "frames": 30},
    {"state": "normal", "frames": 60},
    {"state": "talk_a", "frames": 60},
    {"state": "talk_b", "frames": 60},
]

# 全フォルダ名（ガイド表示用・省略なし）
ALL_10F_FOLDERS = ["normal_10", "blink_10", "talk_10"]
ALL_30F_FOLDERS = ["normal_30", "talk_a_30", "talk_b_30"]
ALL_60F_FOLDERS = ["normal_60", "talk_a_60", "talk_b_60"]


class TutorialDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("DaVinci Resolve 連携手順（読込・配置ガイド）")
        self.geometry("960x860")
        self.resizable(True, True)
        self.grab_set()

        # スライドのデータ定義
        self.slides = [
            {
                "title": "1. 連番PNGの出力が完了しました",
                "text": "現在のフォルダに、キャラクター名で識別される連番PNGフォルダ一式が生成されました。\n\n"
                        "フォルダ名は「 キャラ名_ビデオトラック_オーディオトラック_状態_フレーム数 」です。\n\n"
                        "【10f】 " + " ".join(("キャラ名_"+f) for f in ALL_10F_FOLDERS) + "\n"
                        "【30f】 " + " ".join(("キャラ名_"+f) for f in ALL_30F_FOLDERS) + "\n"
                        "【60f】 " + " ".join(("キャラ名_"+f) for f in ALL_60F_FOLDERS) + "\n\n"
                        "これらをDaVinci Resolveに読み込ませる準備を行います。",
                "image_path": "step1.png"
            },
            {
                "title": "2. Resolveへのシーケンス読み込み設定",
                "text": "1. DaVinci Resolveの「メディア」タブを開きます。\n"
                        "2. 画面左上「メディアストレージ」の右上にある「…（三点リーダ）」をクリックします。\n"
                        "3.「フレーム表示モード」 ＞ 「シーケンス」を選択します。\n"
                        "4. 出力されたフォルダ一式を、下の「メディアプール」へ順にドラッグ＆ドロップします。\n\n"
                        "※これにより、各フォルダが「1本の動画素材（シーケンス素材）」としてResolveに認識されます。\n\n"
                        "■ トラック割り当ての注意\n"
                        "各キャラクターの「ビデオトラック番号」「オーディオトラック番号」はこのGUIで設定した値が\n"
                        "フォルダ名に反映されます。複数キャラを配置する場合は、それぞれ参照する音声トラックを\n"
                        "変えることで、別々の音声に合わせて口パクさせられます。",
                "image_path": "step2.png"
            },
            {
                "title": "3. タイムライン配置と基準位置の設定",
                "text": "1. 読み込んだ各キャラクターの「通常（_normal_10）」シーケンス素材を、そのキャラの\n"
                        "   ビデオトラックに配置します。\n"
                        "2. インスペクタでキャラクターの「ズーム」や「位置（上下左右）」、「反転」\n"
                        "  （左右反転など）を調整します。\n\n"
                        "※後ほど実行する自動化マクロ（スクリプト）は、この配置済み素材の座標情報を\n"
                        "  「ベース（基準）」として口パクや表情バリエーションを自動配置します。",
                "image_path": "step3.png"
            },
            {
                "title": "4. 自動化スクリプトの実行",
                "text": "1. Resolve の「ワークスペース」＞「スクリプト」＞「Utility」から\n"
                        "   character_lip_sync.py を実行します。\n\n"
                        "※ スクリプトのコピーは通常「起動時」に行っていますが、\n"
                        "   起動時の確認で「いいえ／スキップ」を選んだ場合は、\n"
                        "   最新版が反映されないことがあります。その場合はアプリを\n"
                        "   起動し直して「はい（コピー）」を選択してください。",
                "image_path": "step4.png"
            }
        ]

        self.current_index = 0
        self.skip_var = tk.BooleanVar(value=not parent.show_tutorial.get())

        self.create_widgets()
        self.show_slide(0)

    def create_widgets(self):
        self.content_frame = ttk.Frame(self, padding=20)
        self.content_frame.pack(fill=tk.BOTH, expand=True)

        self.lbl_title = ttk.Label(self.content_frame, text="", font=("", 14, "bold"))
        self.lbl_title.pack(anchor=tk.W, pady=(0, 10))

        self.img_frame = ttk.Frame(self.content_frame, width=870, height=480, relief="solid", borderwidth=1)
        self.img_frame.pack_propagate(False)
        self.img_frame.pack(pady=(0, 15))

        self.lbl_image = ttk.Label(self.img_frame, anchor="center")
        self.lbl_image.pack(fill=tk.BOTH, expand=True)

        self.lbl_text = ttk.Label(self.content_frame, text="", font=("", 10), justify=tk.LEFT, wraplength=880)
        self.lbl_text.pack(fill=tk.BOTH, expand=True, anchor=tk.NW)

        self.bottom_frame = ttk.Frame(self, padding=15)
        self.bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.chk_skip = ttk.Checkbutton(self.bottom_frame, text="次回からこのガイドを表示しない", variable=self.skip_var, command=self.on_skip_toggle)
        self.chk_skip.pack(side=tk.LEFT)

        self.btn_next = ttk.Button(self.bottom_frame, text="次へ ＞", command=self.next_slide)
        self.btn_next.pack(side=tk.RIGHT, padx=5)

        self.btn_prev = ttk.Button(self.bottom_frame, text="＜ 前へ", command=self.prev_slide)
        self.btn_prev.pack(side=tk.RIGHT, padx=5)

        self.lbl_page = ttk.Label(self.bottom_frame, text="", font=("", 10))
        self.lbl_page.pack(side=tk.RIGHT, padx=15)

    def show_slide(self, index):
        slide = self.slides[index]
        self.lbl_title.config(text=slide["title"])
        self.lbl_text.config(text=slide["text"])
        self.lbl_page.config(text=f"{index + 1} / {len(self.slides)}")

        if os.path.exists(slide["image_path"]):
            try:
                img = Image.open(slide["image_path"])
                img.thumbnail((868, 478), Image.Resampling.LANCZOS)
                self.tk_img = ImageTk.PhotoImage(img)
                self.lbl_image.config(image=self.tk_img, text="")
            except Exception:
                self.lbl_image.config(image="", text="[ 画像の読み込みに失敗しました ]")
        else:
            self.lbl_image.config(image="", text="[ 関連スクリーンショットの配置エリア ]\n(※同ディレクトリに step1.png ~ step4.png があれば表示されます)")

        if index == 0:
            self.btn_prev.state(["disabled"])
        else:
            self.btn_prev.state(["!disabled"])

        if index == len(self.slides) - 1:
            self.btn_next.config(text="閉じる")
        else:
            self.btn_next.config(text="次へ ＞")

    def next_slide(self):
        if self.current_index < len(self.slides) - 1:
            self.current_index += 1
            self.show_slide(self.current_index)
        else:
            self.destroy()

    def prev_slide(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.show_slide(self.current_index)

    def on_skip_toggle(self):
        self.parent.show_tutorial.set(not self.skip_var.get())
        self.parent.save_config()


class TimelineSettingsDialog(tk.Toplevel):
    """タイムライン設定ダイアログ（タブではなくボタン→ダイアログ）"""
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("タイムライン設定")
        self.geometry("480x440")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        frame = ttk.Frame(self, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        sys_frame = ttk.LabelFrame(frame, text=" 1. システム連携 ", padding=10)
        sys_frame.pack(fill=tk.X, pady=5)
        ttk.Button(sys_frame, text="DaVinci Resolveへスクリプトをコピー", command=self.parent.copy_script_to_resolve).pack(fill=tk.X)

        param_frame = ttk.LabelFrame(frame, text=" 2. アニメーションパラメータ調整 ", padding=10)
        param_frame.pack(fill=tk.X, pady=10)
        ttk.Label(param_frame, text="ベースFPS:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(param_frame, textvariable=self.parent.fps, width=10).grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Label(param_frame, text="まばたき最小間隔 (秒):").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(param_frame, textvariable=self.parent.blink_min, width=10).grid(row=1, column=1, sticky=tk.W, padx=5)
        ttk.Label(param_frame, text="まばたき最大間隔 (秒):").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(param_frame, textvariable=self.parent.blink_max, width=10).grid(row=2, column=1, sticky=tk.W, padx=5)
        ttk.Checkbutton(param_frame, text="可変ブロックサイズを使用（10f/30f/60f）", variable=self.parent.variable_block).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=10)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(16, 4))
        btn_close = ttk.Button(btn_frame, text="OK（設定を保存）", command=self._save_and_close)
        btn_close.pack(side=tk.RIGHT, ipadx=16, ipady=4)

    def _save_and_close(self):
        self.parent.save_config()
        self.parent.update_timeline_settings_label()
        self.destroy()


class CreateCharacterDialog(tk.Toplevel):
    """キャラクター新規作成ダイアログ"""
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("キャラクター新規作成")
        self.geometry("420x260")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        self.chara_id = tk.StringVar()
        self.video_track = tk.IntVar(value=2)
        self.audio_track = tk.IntVar(value=1)

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="キャラクター名（ID）を入力してください", font=("", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
        ttk.Label(frame, text="例: 001 / A / 主人公 など（英数字推奨）", foreground="gray").grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(0, 12))

        ttk.Label(frame, text="キャラクター名:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.entry_name = ttk.Entry(frame, textvariable=self.chara_id, width=24)
        self.entry_name.grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="配置先ビデオトラック:").grid(row=3, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(frame, from_=1, to=16, textvariable=self.video_track, width=8).grid(row=3, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="走査対象オーディオトラック:").grid(row=4, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(frame, from_=1, to=16, textvariable=self.audio_track, width=8).grid(row=4, column=1, sticky=tk.W, padx=5)

        btn_frame = ttk.Frame(self, padding=15)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(btn_frame, text="作成", command=self._create).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="キャンセル", command=self.destroy).pack(side=tk.RIGHT, padx=5)

        self.entry_name.focus_set()

    def _create(self):
        name = self.chara_id.get().strip()
        if not name:
            messagebox.showwarning("入力エラー", "キャラクター名を入力してください。", parent=self)
            return
        if name in self.parent.characters:
            messagebox.showwarning("重複エラー", f"キャラクター名 '{name}' は既に使用されています。\n別の名前を入力してください。", parent=self)
            return

        self.parent.characters[name] = {
            "video_track": int(self.video_track.get()),
            "audio_track": int(self.audio_track.get()),
        }
        self.parent.refresh_character_combo()
        self.parent.select_character(name)
        self.parent.save_config()
        messagebox.showinfo("成功", f"キャラクター '{name}' を作成しました。", parent=self)
        self.destroy()


class ProgressDialog(tk.Toplevel):
    """連番生成中のプログレス表示ダイアログ（モーダル）"""
    def __init__(self, parent, max_steps):
        super().__init__(parent)
        self.parent = parent
        self.title("連番PNGを生成しています…")
        self.geometry("460x150")
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # X で閉じられないように

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        self.lbl_status = ttk.Label(frame, text="準備中…", font=("", 11))
        self.lbl_status.pack(anchor=tk.W, pady=(0, 12))

        self.progress = ttk.Progressbar(frame, maximum=max_steps, mode="determinate")
        self.progress.pack(fill=tk.X)

        self.lbl_count = ttk.Label(frame, text="0 / 0", foreground="gray")
        self.lbl_count.pack(anchor=tk.E, pady=(6, 0))

        self.max_steps = max_steps
        self.current = 0

    def set_status(self, text):
        self.lbl_status.config(text=text)
        self.update_idletasks()

    def set_progress(self, completed):
        self.current = completed
        self.progress["value"] = completed
        self.lbl_count.config(text=f"{completed} / {self.max_steps}")
        self.update_idletasks()


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("キャラ口パク・まばたき自動化ツール (v2.0) マルチキャラ対応")
        self.geometry("1280x900")

        # PSD・レイヤー状態管理
        self.psd = None
        self.layer_flat_map = {}
        self.layer_vis_states = {}
        self.layer_is_radio = {}

        self.snapshot_normal = None
        self.snapshot_blink = None
        self.snapshot_talk = None

        # PNG版マスター画像（版管理チェック用にも保持）
        self.png_master_normal = None
        self.png_master_blink = None
        self.png_master_talk = None

        # 版管理フラグ（オリジナルPNGと差異があるか）
        self.version_status = {"normal": "unknown", "blink": "unknown", "talk": "unknown"}

        self.fps = tk.IntVar(value=60)
        self.blink_min = tk.DoubleVar(value=5.0)
        self.blink_max = tk.DoubleVar(value=10.0)
        self.psd_path = tk.StringVar()
        self.show_tutorial = tk.BooleanVar(value=True)
        self.variable_block = tk.BooleanVar(value=True)

        # PNG・JPEG状態管理
        self.png_path = tk.StringVar()
        self.png_image = None
        self.current_mode = "png"  # "psd" or "png"
        self.source_var = tk.StringVar(value="png")  # 切替UI（png/psd）

        # キャラクター管理
        self.characters = {}                 # {name: {video_track, audio_track}}
        self.current_character = tk.StringVar()

        # アイコンビットマップ
        self.img_checked = tk.BitmapImage(data="""
#define im_width 12
#define im_height 12
static unsigned char im_bits[] = {
   0xff,0x0f, 0x01,0x08, 0x01,0x08, 0x01,0x09, 0x81,0x09, 0xc1,0x08,
   0x61,0x08, 0x31,0x08, 0x19,0x08, 0x0d,0x08, 0x01,0x08, 0xff,0x0f};
""")
        self.img_unchecked = tk.BitmapImage(data="""
#define im_width 12
#define im_height 12
static unsigned char im_bits[] = {
   0xff,0x0f, 0x01,0x08, 0x01,0x08, 0x01,0x08, 0x01,0x08, 0x01,0x08,
   0x01,0x08, 0x01,0x08, 0x01,0x08, 0x01,0x08, 0x01,0x08, 0xff,0x0f};
""")
        self.img_radio_on = tk.BitmapImage(data="""
#define im_width 12
#define im_height 12
static unsigned char im_bits[] = {
   0x3c,0x00, 0x42,0x00, 0x81,0x00, 0x81,0x00, 0x99,0x00, 0xbd,0x00,
   0xbd,0x00, 0x99,0x00, 0x81,0x00, 0x81,0x00, 0x42,0x00, 0x3c,0x00};
""")
        self.img_radio_off = tk.BitmapImage(data="""
#define im_width 12
#define im_height 12
static unsigned char im_bits[] = {
   0x3c,0x00, 0x42,0x00, 0x81,0x00, 0x81,0x00, 0x81,0x00, 0x81,0x00,
   0x81,0x00, 0x81,0x00, 0x81,0x00, 0x81,0x00, 0x42,0x00, 0x3c,0x00};
""")

        self.load_config()
        self.create_widgets()
        self.run_startup_check()
        self.check_versions_after_load()

    def log(self, level, message):
        text = f"[{level.upper()}] {message}"
        print(text)
        _log(text)

    # ==========================================================================
    # 起動時チェック
    # ==========================================================================
    def script_paths(self):
        local = os.path.join(_app_dir(), RESOLVE_SCRIPT_NAME)
        remote = os.path.join(_find_resolve_script_dir(), RESOLVE_SCRIPT_NAME)
        return local, remote

    def ensure_local_script(self):
        """exe実行時に内包したcharacter_lip_sync.pyをexe横へ展開する。

        開発時はローカルに既にあるため何もしない。
        """
        if not getattr(sys, "frozen", False):
            return True
        try:
            base = getattr(sys, "_MEIPASS", None)
            if not base:
                return False
            bundled = os.path.join(base, RESOLVE_SCRIPT_NAME)
            if not os.path.exists(bundled):
                return False
            local, _ = self.script_paths()
            shutil.copy2(bundled, local)
            return True
        except Exception as e:
            _log(f"[ERROR] ensure_local_script: {e}")
            return False

    def scripts_differ(self):
        local, remote = self.script_paths()
        if not os.path.exists(local) or not os.path.exists(remote):
            return True
        try:
            with open(local, "rb") as f:
                h1 = hashlib.md5(f.read()).hexdigest()
            with open(remote, "rb") as f:
                h2 = hashlib.md5(f.read()).hexdigest()
            return h1 != h2
        except Exception as e:
            self.log("error", f"スクリプト比較失敗: {e}")
            return True

    def run_startup_check(self):
        self.update_idletasks()
        self.after(200, self._startup_check_now)

    def _startup_check_now(self):
        if not self.ensure_local_script():
            self.log("warn", "内包スクリプトのローカル展開に失敗しました。")
        local, remote = self.script_paths()
        if not os.path.exists(local):
            messagebox.showwarning(
                "スクリプトが見つかりません",
                f"ローカルに '{RESOLVE_SCRIPT_NAME}' が見つかりません。\n"
                "Resolve連携スクリプトが無いと自動化を実行できません。\n\n"
                "スクリプトを用意してから再度お試しください。",
                parent=self
            )
            return

        if not self.scripts_differ():
            self.log("info", "Resolve側スクリプトは最新です。")
            return

        # 差異あり → コピー確認
        ans = messagebox.askyesnocancel(
            "ファイルコピーが必要です",
            "ローカルの character_lip_sync.py は Resolve 側のものと異なります。\n\n"
            "最新のスクリプトを Resolve 側にコピーしますか？\n"
            f"\n  ローカル: {local}\n  Resolve: {remote}\n\n"
            "「はい」でコピー、「いいえ」で今後の起動確認をスキップ、「キャンセル」で次回また確認します。",
            parent=self
        )
        if ans is None:  # キャンセル → 次回また確認（何もしない）
            return
        if ans:  # はい
            try:
                os.makedirs(os.path.dirname(remote), exist_ok=True)
                shutil.copy2(local, remote)
                messagebox.showinfo("成功", "最新のスクリプトを Resolve 側にコピーしました。", parent=self)
                return
            except Exception as e:
                messagebox.showerror("コピー失敗", f"コピーに失敗しました。\n{e}", parent=self)
                # 失敗したので続行可否を問う
                self._ask_force_continue()
                return
        else:  # いいえ → 強行 or 終了
            self._ask_force_continue()

    def _ask_force_continue(self):
        ans = messagebox.askyesno(
            "警告：スクリプトが不一致のまま続行",
            "スクリプトをコピーしないと、Resolve側のスクリプトが古い可能性があり\n"
            "「動かない」または「誤動作」を引き起こす恐れがあります。\n\n"
            "それでも続行しますか？\n\n"
            "「はい」= そのまま強行して続行\n「いいえ」= アプリケーションを終了",
            parent=self
        )
        if not ans:
            self.log("info", "ユーザーによりアプリケーションを終了します。")
            self.destroy()

    # ==========================================================================
    # GUI構築
    # ==========================================================================
    def create_widgets(self):
        # clamテーマに切り替え（ttkボタンで背景色を反映させるため）
        self.style = ttk.Style(self)
        try:
            # self.style.theme_use("clam")
            # self.style.theme_use("default")
            # self.style.theme_use("winnative")
            self.style.theme_use("vista")
            # self.style.theme_use("alt")
            # self.style.theme_use("xpnative")
        except Exception as e:
            self.log("error", f"テーマ切替失敗: {e}")

        # ------- トップツールバー --------
        toolbar = ttk.Frame(self, padding=(10, 8, 10, 4))
        toolbar.pack(fill=tk.X)

        self.lbl_timeline_settings = ttk.Button(
            toolbar,
            text="タイムライン設定：未設定",
            command=self.open_timeline_settings,
        )
        self.lbl_timeline_settings.pack(side=tk.LEFT)
        self.update_timeline_settings_label()

        # ------- メインエリア --------
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))

        self.tab_main = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.tab_main, text=" キャラクター設定・連番生成 ")
        self.build_main_tab()

    def update_timeline_settings_label(self):
        fps = self.fps.get()
        bmin = self.blink_min.get()
        bmax = self.blink_max.get()
        vblock = "可変" if self.variable_block.get() else "固定10f"
        self.lbl_timeline_settings.config(
            text=f"タイムライン設定：FPS {fps} / まばたき {bmin}〜{bmax}s / {vblock}"
        )

    def open_timeline_settings(self):
        TimelineSettingsDialog(self)

    def build_main_tab(self):
        # =================
        # 0. キャラクター管理
        # =================
        char_frame = ttk.LabelFrame(self.tab_main, text=" 1. キャラクター選択 ", padding=10)
        char_frame.pack(fill=tk.X, pady=(0, 8))

        inner = ttk.Frame(char_frame)
        inner.pack(fill=tk.X)

        ttk.Label(inner, text="キャラクター:").pack(side=tk.LEFT)
        self.chara_combo = ttk.Combobox(inner, state="readonly", textvariable=self.current_character, width=20)
        self.chara_combo.pack(side=tk.LEFT, padx=8)
        self.chara_combo.bind("<<ComboboxSelected>>", self.on_character_selected)

        ttk.Button(inner, text="＋ 新規作成", command=self.open_create_character).pack(side=tk.LEFT, padx=5)
        ttk.Button(inner, text="削除", command=self.delete_character).pack(side=tk.LEFT, padx=5)

        self.lbl_char_detail = ttk.Label(inner, text="", foreground="gray")
        self.lbl_char_detail.pack(side=tk.LEFT, padx=12)

        # =================
        # 2. 画像ソース（PNG/JPG または PSD）
        # =================
        source_frame = ttk.LabelFrame(self.tab_main, text=" ２．立ち絵（ソース画像）の設定 ", padding=10)
        source_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            source_frame,
            text="通常・目閉じ・口パクの画像は、右の「状態登録と出力」からそれぞれ選択してください。\n"
                 "PSDから合成して使う場合は、上の「PSD から合成して作る」を選んでください。",
            foreground="black", font=("", 10), justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 4))

        # =================
        # 3. 状態の登録・プレビュー・出力
        # =================
        work_frame = ttk.LabelFrame(self.tab_main, text=" ３．状態の登録 ", padding=10)
        work_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        # 画像ソース切替（PNG/JPG と PSD）
        source_switch = ttk.Frame(work_frame)
        source_switch.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(source_switch, text="使用する画像の種類:",
                  foreground="gray", font=("", 9)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(source_switch, text="PNG/JPG 画像から選ぶ", value="png",
                        variable=self.source_var, command=self.on_source_switch).pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(source_switch, text="PSD から合成して作る", value="psd",
                        variable=self.source_var, command=self.on_source_switch).pack(side=tk.LEFT, padx=6)

        paned = ttk.PanedWindow(work_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # 左：レイヤー構造 と リアルタイムプレビュー（横並び）
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=6)

        left_paned = ttk.PanedWindow(left_frame, orient=tk.HORIZONTAL)
        left_paned.pack(fill=tk.BOTH, expand=True)

        self.layer_tree_frame = ttk.LabelFrame(left_paned, text=" レイヤー構造（アイコンをクリックしてON/OFF） ※PSDモード ", padding=4)
        left_paned.add(self.layer_tree_frame, weight=3)

        # PNG/JPGモード時に表示するプレースホルダー表記
        self.lbl_png_mode = ttk.Label(
            self.layer_tree_frame,
            text="PNG/JPG選択モード",
            foreground="gray",
        )

        self.tree_wrap = ttk.Frame(self.layer_tree_frame)
        self.tree_wrap.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(self.tree_wrap, selectmode="browse", show="tree")
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        self.tree_scrollbar = ttk.Scrollbar(self.tree_wrap, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree_scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.tree.configure(yscrollcommand=self.tree_scrollbar.set)
        self.tree.bind("<Button-1>", self.on_tree_click)

        # PSDツリー表示時に一番下に表示するキャンセルボタン
        self.btn_cancel_psd = ttk.Button(
            self.layer_tree_frame,
            text="psdからの生成をキャンセルしてpng/jpgから選択する",
            command=self.on_cancel_psd,
        )

        # プレビュー画像の最大サイズ（表示領域に合わせてリサイズ）
        self.preview_box = (500, 380)

        center_frame = ttk.LabelFrame(left_paned, text=" リアルタイムプレビュー ", padding=4)
        # 画像サイズで枠が拡大しないよう、固定サイズにして子供（画像）に合わせて伸びないようにする
        center_frame.pack_propagate(False)
        center_frame.config(width=self.preview_box[0] + 12, height=self.preview_box[1] + 12)
        left_paned.add(center_frame, weight=2)
        self.lbl_preview = ttk.Label(center_frame, anchor="center")
        self.lbl_preview.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self._preview_source_img = None
        # ウィンドウリサイズ時にプレビューを表示領域に合わせて再縮小
        self.lbl_preview.bind("<Configure>", self._on_preview_resize)
        # プレビューをクリックしたら大きめダイアログで拡大表示
        self.lbl_preview.bind("<Button-1>", lambda e: self._open_preview_zoom())

        # 右：状態登録・出力
        right_frame = ttk.LabelFrame(paned, text=" 状態登録と出力 ", padding=10)
        paned.add(right_frame, weight=3)

        # 通常
        self.btn_snap_normal = ttk.Button(right_frame, text="通常状態の画像を選択", command=lambda: self._state_action("normal"))
        self.btn_snap_normal.pack(fill=tk.X, pady=3)
        self.lbl_snap_normal_frame = ttk.Frame(right_frame)
        self.lbl_snap_normal_frame.pack(fill=tk.X, pady=(0, 6))
        self.lbl_snap_normal = ttk.Label(self.lbl_snap_normal_frame, text="通常: 未記憶", foreground="gray")
        self.lbl_snap_normal.pack(side=tk.LEFT)
        # 枠付きクリック可能なサムネイル（クリックで拡大表示）
        self.snap_normal_border = tk.Frame(self.lbl_snap_normal_frame, bd=1, relief="solid", cursor="hand2")
        self.snap_normal_border.pack(side=tk.RIGHT)
        self.snap_preview_normal = ttk.Label(self.snap_normal_border)
        self.snap_preview_normal.pack(padx=1, pady=1)
        self.snap_preview_normal.bind("<Button-1>", lambda e, m="normal": self._open_snapshot_dialog(m))
        self.snap_normal_border.bind("<Button-1>", lambda e, m="normal": self._open_snapshot_dialog(m))

        # 目閉じ
        self.btn_snap_blink = ttk.Button(right_frame, text="目閉じ状態の画像を選択", command=lambda: self._state_action("blink"))
        self.btn_snap_blink.pack(fill=tk.X, pady=3)
        self.lbl_snap_blink_frame = ttk.Frame(right_frame)
        self.lbl_snap_blink_frame.pack(fill=tk.X, pady=(0, 6))
        self.lbl_snap_blink = ttk.Label(self.lbl_snap_blink_frame, text="目閉じ: 未記憶", foreground="gray")
        self.lbl_snap_blink.pack(side=tk.LEFT)
        self.snap_blink_border = tk.Frame(self.lbl_snap_blink_frame, bd=1, relief="solid", cursor="hand2")
        self.snap_blink_border.pack(side=tk.RIGHT)
        self.snap_preview_blink = ttk.Label(self.snap_blink_border)
        self.snap_preview_blink.pack(padx=1, pady=1)
        self.snap_preview_blink.bind("<Button-1>", lambda e, m="blink": self._open_snapshot_dialog(m))
        self.snap_blink_border.bind("<Button-1>", lambda e, m="blink": self._open_snapshot_dialog(m))

        # 口開け
        self.btn_snap_talk = ttk.Button(right_frame, text="口開け状態の画像を選択", command=lambda: self._state_action("talk"))
        self.btn_snap_talk.pack(fill=tk.X, pady=3)
        self.lbl_snap_talk_frame = ttk.Frame(right_frame)
        self.lbl_snap_talk_frame.pack(fill=tk.X, pady=(0, 6))
        self.lbl_snap_talk = ttk.Label(self.lbl_snap_talk_frame, text="口開け: 未記憶", foreground="gray")
        self.lbl_snap_talk.pack(side=tk.LEFT)
        self.snap_talk_border = tk.Frame(self.lbl_snap_talk_frame, bd=1, relief="solid", cursor="hand2")
        self.snap_talk_border.pack(side=tk.RIGHT)
        self.snap_preview_talk = ttk.Label(self.snap_talk_border)
        self.snap_preview_talk.pack(padx=1, pady=1)
        self.snap_preview_talk.bind("<Button-1>", lambda e, m="talk": self._open_snapshot_dialog(m))
        self.snap_talk_border.bind("<Button-1>", lambda e, m="talk": self._open_snapshot_dialog(m))

        # 出力（状態の説明のみ。生成操作はセクション4へ）
        ttk.Label(
            right_frame,
            text="※ 「通常」と「目閉じまたは口開け」が設定されると\n「４．連番PNG生成」で生成できるようになります。",
            foreground="gray", justify=tk.LEFT, wraplength=260
        ).pack(fill=tk.X, side=tk.BOTTOM, pady=(6, 4))

        # =================
        # 4. 連番PNG生成（常時表示）
        # =================
        gen_frame = ttk.LabelFrame(self.tab_main, text=" ４．連番PNG生成 ", padding=10)
        gen_frame.pack(fill=tk.X, pady=(8, 0))

        # 3状態の設定状況サマリー
        gen_row = ttk.Frame(gen_frame)
        gen_row.pack(fill=tk.X)
        self.gen_status_normal = ttk.Label(gen_row, text="通常: 未設定", foreground="gray")
        self.gen_status_normal.pack(side=tk.LEFT, padx=(0, 10))
        self.gen_status_blink = ttk.Label(gen_row, text="目閉じ: 未設定", foreground="gray")
        self.gen_status_blink.pack(side=tk.LEFT, padx=10)
        self.gen_status_talk = ttk.Label(gen_row, text="口開け: 未設定", foreground="gray")
        self.gen_status_talk.pack(side=tk.LEFT, padx=10)

        # チェックボックス＋「今すぐガイド表示」の小ボタン（右に配置）
        tutorial_row = ttk.Frame(gen_frame)
        tutorial_row.pack(fill=tk.X, pady=(8, 0))
        self.chk_show_tutorial = ttk.Checkbutton(
            tutorial_row,
            text="連番PNG生成時にガイドを自動表示する",
            variable=self.show_tutorial,
            command=self.save_config,
        )
        self.chk_show_tutorial.pack(side=tk.LEFT)
        self.btn_guide = ttk.Button(
            tutorial_row,
            text="今すぐガイド表示",
            command=lambda: TutorialDialog(self),
        )
        self.btn_guide.pack(side=tk.RIGHT)

        self.btn_generate = ttk.Button(
            gen_frame,
            text="［ アニメーション生成を開始 ］",
            command=self.open_preview_dialog,
            state="disabled",
            style="TButton",
            takefocus=True,
        )
        self.btn_generate.pack(fill=tk.X, pady=(8, 0), ipady=8)

        # 初期状態は PNG/画像選択モードの表示に合わせる
        self._update_source_ui()
        self._update_gen_status()

        self.refresh_character_combo()

    # ==========================================================================
    # キャラクター管理
    # ==========================================================================
    def refresh_character_combo(self):
        names = list(self.characters.keys())
        self.chara_combo["values"] = names
        if names:
            if self.current_character.get() in names:
                pass
            elif self.current_character.get():
                self.current_character.set(names[0])
            else:
                self.current_character.set(names[0])
            self.on_character_selected()
        else:
            self.current_character.set("")
            self.lbl_char_detail.config(text="")
            self.btn_generate.config(state="disabled")

    def select_character(self, name):
        self.current_character.set(name)
        self.on_character_selected()

    def on_character_selected(self, event=None):
        name = self.current_character.get()
        if not name or name not in self.characters:
            self.lbl_char_detail.config(text="")
            return
        info = self.characters[name]
        self.lbl_char_detail.config(
            text=f"ビデオトラック: {info['video_track']} / 音声トラック: {info['audio_track']}"
        )
        self.refresh_character_settings_fields(info)
        self.check_generate_enabled()

    def refresh_character_settings_fields(self, info):
        # 現在は詳細表示のみ（作成ダイアログで設定）。拡張用フック。
        pass

    def open_create_character(self):
        CreateCharacterDialog(self)

    def delete_character(self):
        name = self.current_character.get()
        if not name:
            return
        ans = messagebox.askyesno("確認", f"キャラクター '{name}' を削除しますか？\n（生成済みPNGフォルダは削除されません）")
        if not ans:
            return
        del self.characters[name]
        self.current_character.set("")
        self.refresh_character_combo()
        self.save_config()

    def current_chara_id(self):
        return self.current_character.get().strip() if self.current_character.get() else ""

    def current_chara_info(self):
        name = self.current_chara_id()
        if name and name in self.characters:
            return self.characters[name]
        return {"video_track": 2, "audio_track": 1}

    def folder_base(self):
        """{chara_id}_{video_track}_{audio_track}"""
        info = self.current_chara_info()
        return f"{self.current_chara_id()}_{info['video_track']}_{info['audio_track']}"

    # ==========================================================================
    # ロジック
    # ==========================================================================

    # ---- 画像ソースのモード切替 ----
    def _update_source_ui(self):
        """current_mode に応じて、レイヤー欄の表示と状態ボタンのラベル/動作を切り替える"""
        self.source_var.set(self.current_mode)
        png = self.current_mode == "png"
        # レイヤー欄
        if png:
            self.layer_tree_frame.config(text=" 画像モード（レイヤーなし） ")
            self.tree_wrap.pack_forget()
            self.btn_cancel_psd.pack_forget()
            self.lbl_png_mode.pack(fill=tk.X, side=tk.TOP, ipady=40, pady=6, padx=8)
        else:
            self.layer_tree_frame.config(text=" レイヤー構造（アイコンをクリックしてON/OFF） ")
            self.lbl_png_mode.pack_forget()
            self.tree_wrap.pack(fill=tk.BOTH, expand=True)
            self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
            self.tree_scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
            if self.psd:
                self.btn_cancel_psd.pack(fill=tk.X, side=tk.BOTTOM, ipady=3)
            else:
                self.btn_cancel_psd.pack_forget()
        # 状態ボタン（ラベルと動作をモードに追随）
        if png:
            self.btn_snap_normal.config(text="通常状態の画像を選択")
            self.btn_snap_blink.config(text="目閉じ状態の画像を選択")
            self.btn_snap_talk.config(text="口開け状態の画像を選択")
            self.btn_snap_normal["command"] = lambda m="normal": self._state_action("normal")
            self.btn_snap_blink["command"] = lambda m="blink": self._state_action("blink")
            self.btn_snap_talk["command"] = lambda m="talk": self._state_action("talk")
        else:
            self.btn_snap_normal.config(text="現在の見た目を【通常】として記憶")
            self.btn_snap_blink.config(text="現在の見た目を【目閉じ】として記憶")
            self.btn_snap_talk.config(text="現在の見た目を【口開け】として記憶")
            self.btn_snap_normal["command"] = lambda m="normal": self.save_snapshot("normal")
            self.btn_snap_blink["command"] = lambda m="blink": self.save_snapshot("blink")
            self.btn_snap_talk["command"] = lambda m="talk": self.save_snapshot("talk")

    def on_source_switch(self):
        """セクション3のPng⇔PSD 切替ラジオボタン"""
        choice = self.source_var.get()
        if choice == "psd":
            if self.psd is None:
                # PSD未読込なら先にファイルを選んでもらう
                self.on_psd_generate()
            self.current_mode = "psd" if self.psd else "png"
            if self.current_mode == "png":
                self.source_var.set("png")
        else:
            self.current_mode = "png"
        self._update_source_ui()

    def _update_gen_status(self):
        """セクション4の3状態の設定状況サマリーを更新"""
        texts = {"normal": "通常", "blink": "目閉じ", "talk": "口開け"}
        states = {"normal": self.snapshot_normal, "blink": self.snapshot_blink, "talk": self.snapshot_talk}
        labels = {"normal": self.gen_status_normal, "blink": self.gen_status_blink, "talk": self.gen_status_talk}
        for mode, lbl in labels.items():
            if states[mode] is not None:
                lbl.config(text=f"{texts[mode]}: 設定済み", foreground="green")
            else:
                lbl.config(text=f"{texts[mode]}: 未設定", foreground="gray")

    def _state_action(self, mode):
        """状態ボタンの共通動作（モードにより分岐）"""
        if self.current_mode == "png":
            self._pick_state_image(mode)
        else:
            self.save_snapshot(mode)

    def _pick_state_image(self, mode):
        """PNG/JPGモード: 指定状態用の画像ファイルを選択して記憶する"""
        file_path = filedialog.askopenfilename(
            title="画像ファイルを選択",
            filetypes=[("画像ファイル", "*.png *.jpg *.jpeg *.bmp *.gif"), ("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg")]
        )
        if not file_path:
            return
        try:
            img = Image.open(file_path).convert("RGBA")
        except Exception as e:
            self.log("error", f"画像の解析中にエラーが発生しました: {e}")
            messagebox.showerror("エラー", f"画像を開けませんでした: {e}")
            return
        self.png_image = img
        self.current_mode = "png"
        self.psd = None
        self._set_snapshot(mode, img.copy())
        self._update_snapshot_preview(mode)
        self.refresh_preview_image()
        self.diff_masters()
        self.check_generate_enabled()
        self.log("info", f"【{mode}】の画像を選択しました: {file_path}")
        self.save_config()

    def on_psd_generate(self):
        """PSDファイルを選択して読み込み、PSDモードへ移行する"""
        file_path = filedialog.askopenfilename(title="PSDファイルを選択", filetypes=[("Photoshop Files", "*.psd")])
        if not file_path:
            return
        self.load_psd(file_path)
        self._update_source_ui()

    def on_cancel_psd(self):
        """PSD生成をキャンセルして PNG/JPG 選択モードに戻す"""
        self.psd = None
        self.psd_path.set("")
        self.clear_snapshots()
        self.current_mode = "png"
        self._update_source_ui()
        self.log("info", "PSDモードをキャンセルし、画像（PNG/JPG）選択モードに戻しました。")

    def load_png(self, *a, **k):
        # 従来の一括PNG読込は廃止。各状態ボタンから _pick_state_image で選択する
        pass

    def load_psd(self, file_path=None):
        if file_path is None:
            file_path = filedialog.askopenfilename(title="PSDファイルを選択", filetypes=[("Photoshop Files", "*.psd")])
            if not file_path:
                return

        old_psd_path = self.psd_path.get()
        self.psd_path.set(file_path)
        if old_psd_path != file_path:
            self.clear_snapshots()
        self.log("info", f"PSDのパースを開始します: {file_path}")

        try:
            psd = PSDImage.open(file_path, encoding=_PSD_ENCODING)
            self.psd = psd

            for item in self.tree.get_children():
                self.tree.delete(item)
            self.layer_flat_map.clear()
            self.layer_vis_states.clear()
            self.layer_is_radio.clear()

            def add_layer(parent_node, layer, is_inside_radio_group=False):
                node_id = str(id(layer))
                self.layer_flat_map[node_id] = layer
                self.layer_vis_states[node_id] = layer.is_visible()
                self.layer_is_radio[node_id] = is_inside_radio_group

                img = self.get_node_image(node_id)
                self.tree.insert(parent_node, tk.END, iid=node_id, text=layer.name, image=img, open=False)

                if layer.is_group():
                    next_radio_flag = layer.name.startswith("!") or is_inside_radio_group
                    for sub_layer in layer:
                        add_layer(node_id, sub_layer, next_radio_flag)

            for layer in self.psd:
                add_layer("", layer, False)

            self.current_mode = "psd"
            self.png_image = None
            self.log("info", f"ツリー構築完了。総レイヤー(ノード)数: {len(self.layer_flat_map)}")
            self._update_source_ui()
            self.refresh_preview_image()
            messagebox.showinfo("完了", "PSDファイルを読み込みました。")
        except Exception as e:
            self.psd = None
            self.psd_path.set("")
            self.current_mode = "png"
            self._update_source_ui()
            self.log("error", f"PSDの解析中に致命的なエラーが発生しました: {e}")
            messagebox.showerror("エラー", f"PSDを読み込めませんでした: {e}")

    def get_node_image(self, node_id):
        is_on = self.layer_vis_states[node_id]
        if self.layer_is_radio[node_id]:
            return self.img_radio_on if is_on else self.img_radio_off
        else:
            return self.img_checked if is_on else self.img_unchecked

    def on_tree_click(self, event):
        item_id = self.tree.identify_row(event.y)
        element = self.tree.identify_element(event.x, event.y)

        if not item_id or item_id not in self.layer_vis_states:
            return

        if element == "image":
            layer = self.layer_flat_map[item_id]
            old_state = self.layer_vis_states[item_id]

            if self.layer_is_radio[item_id]:
                parent = self.tree.parent(item_id)
                siblings = self.tree.get_children(parent)
                for sib_id in siblings:
                    self.layer_vis_states[sib_id] = (sib_id == item_id)
                    self.tree.item(sib_id, image=self.get_node_image(sib_id))
                self.log("info", f"【ラジオ選択】グループ内変更 -> 選択レイヤー: '{layer.name}'")
            else:
                self.layer_vis_states[item_id] = not self.layer_vis_states[item_id]
                self.tree.item(item_id, image=self.get_node_image(item_id))
                self.log("info", f"【チェック切替】レイヤー: '{layer.name}' -> {old_state} から {self.layer_vis_states[item_id]} に変更")

            self.refresh_preview_image()

    # ==========================================================================
    # 画像合成
    # ==========================================================================
    def generate_composite(self, custom_states=None):
        if self.current_mode == "png":
            if self.png_image is None:
                return None
            if isinstance(custom_states, Image.Image):
                return custom_states.copy()
            return self.png_image.copy()

        if not self.psd:
            return None

        states = custom_states if custom_states is not None else self.layer_vis_states
        canvas = Image.new("RGBA", (self.psd.width, self.psd.height), (0, 0, 0, 0))

        def composite_recursive(layer_or_group):
            node_id = str(id(layer_or_group))

            if node_id in states:
                is_visible = states[node_id]
            else:
                is_visible = layer_or_group.is_visible()

            if not is_visible:
                return []

            layers_to_draw = []
            if layer_or_group.is_group():
                for sub in layer_or_group:
                    layers_to_draw.extend(composite_recursive(sub))
            else:
                layers_to_draw.append(layer_or_group)

            return layers_to_draw

        draw_list = []
        for layer in self.psd:
            draw_list.extend(composite_recursive(layer))

        for layer in draw_list:
            try:
                layer_img = layer.topil()
                if layer_img:
                    left, top, right, bottom = layer.bbox
                    if right > left and bottom > top:
                        canvas.alpha_composite(
                            layer_img.convert("RGBA"),
                            (left, top)
                        )
            except Exception as e:
                self.log("error", f"レイヤー描画失敗: {layer.name} - {e}")

        self.log("info", f"手動レイヤーマージ完了。描画パーツ数: {len(draw_list)}")
        return canvas

    def refresh_preview_image(self):
        # 現在の合成状態を取得（PSD=現在のツリー選択状態 / PNG=選択画像）して静止表示
        img = self.generate_composite()
        if img is not None:
            self._preview_source_img = img.convert("RGBA")
            self._fit_preview()

    def _on_preview_resize(self, event=None):
        # ウィンドウリサイズ時にもプレビューを表示領域に合わせて再縮小する
        if self._preview_source_img is not None:
            self._fit_preview()

    def _fit_preview(self):
        """表示ラベルの実際の大きさに合わせてプレビュー画像をリサイズ（崩れないように）"""
        if self._preview_source_img is None:
            return
        try:
            self.update_idletasks()
            w = self.lbl_preview.winfo_width()
            h = self.lbl_preview.winfo_height()
            if w <= 10 or h <= 10:
                # まだレイアウト確定前は上限で表示
                w, h = self.preview_box
            # 画像で枠が肥大化しないよう、表示サイズはプレビュー枠を上限にする
            w = min(w, self.preview_box[0])
            h = min(h, self.preview_box[1])
            img = self._preview_source_img.copy()
            img.thumbnail((w, h), Image.Resampling.LANCZOS)
            self.tk_preview_img = ImageTk.PhotoImage(img)
            self.lbl_preview.config(image=self.tk_preview_img)
        except Exception as e:
            self.log("warn", f"プレビュー表示に失敗しました: {e}")

    def _open_preview_zoom(self):
        """プレビューを拡大表示する別ウィンドウ（閉じるボタン付き）"""
        if self._preview_source_img is None:
            return
        dialog = tk.Toplevel(self)
        dialog.title("プレビュー（拡大表示）")
        dialog.transient(self)
        dialog.geometry("560x640")
        dialog.grab_set()

        disp = self._preview_source_img.copy()
        disp.thumbnail((520, 520), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(disp)
        dialog._photo = photo

        lbl = ttk.Label(dialog, image=photo)
        lbl.pack(pady=15)
        ttk.Button(dialog, text="閉じる", command=dialog.destroy).pack(side=tk.BOTTOM, pady=12, ipadx=12, ipady=3)

    # ==========================================================================
    # 状態の登録・版管理
    # ==========================================================================
    def current_composite_image(self):
        """現在の見た目の合成画像（PNG/PSD共通）"""
        return self.generate_composite()

    def save_snapshot(self, mode):
        if not self.psd and not self.png_image:
            return
        if self.current_mode == "png":
            if self.png_image is None:
                return
            current_snapshot = self.png_image.copy()
        else:
            current_snapshot = dict(self.layer_vis_states)

        self._set_snapshot(mode, current_snapshot)

        # 状態欄のプレビュー画像を表示
        self._update_snapshot_preview(mode)
        # リアルタイムプレビューのアニメ用フレームを更新
        self.refresh_preview_image()

        # 版管理チェック（オリジナルと差異があれば未適用表示）
        self.diff_masters()

        # 生成可否の更新
        self.check_generate_enabled()

        self.log("info", f"【スナップショット】状態 '{mode}' を保存しました。")

    def _set_snapshot(self, mode, snapshot):
        if mode == "normal":
            self.snapshot_normal = snapshot
            self.lbl_snap_normal.config(text="通常: 記憶済み (OK)", foreground="green")
        elif mode == "blink":
            self.snapshot_blink = snapshot
            self.lbl_snap_blink.config(text="目閉じ: 記憶済み (OK)", foreground="green")
        elif mode == "talk":
            self.snapshot_talk = snapshot
            self.lbl_snap_talk.config(text="口開け: 記憶済み (OK)", foreground="green")

    def _snapshot_to_image(self, snapshot):
        if self.current_mode == "png":
            return snapshot.copy()
        return self.generate_composite(snapshot)

    def _update_snapshot_preview(self, mode):
        snap = {"normal": self.snapshot_normal, "blink": self.snapshot_blink, "talk": self.snapshot_talk}[mode]
        label = {"normal": self.snap_preview_normal, "blink": self.snap_preview_blink, "talk": self.snap_preview_talk}[mode]
        if snap is None:
            label.config(image="")
            return
        img = self._snapshot_to_image(snap)
        if img is None:
            return
        img.thumbnail((56, 56), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        label.config(image=photo)
        # 参照保持
        if mode == "normal":
            self._tk_snap_normal = photo
        elif mode == "blink":
            self._tk_snap_blink = photo
        else:
            self._tk_snap_talk = photo

    def _open_snapshot_dialog(self, mode):
        """記憶したスナップショットを拡大表示するダイアログ（閉じるボタン付き）"""
        snap = {"normal": self.snapshot_normal, "blink": self.snapshot_blink, "talk": self.snapshot_talk}[mode]
        if snap is None:
            return
        title = {"normal": "通常", "blink": "目閉じ", "talk": "口開け"}[mode]
        img = self._snapshot_to_image(snap)
        if img is None:
            return
        dialog = tk.Toplevel(self)
        dialog.title(f"{title}の拡大表示")
        dialog.transient(self)
        dialog.grab_set()

        # 原寸を基準に、ある程度の大きさまで拡大（ウィンドウに収まるよう調整）
        disp = img.copy()
        disp.thumbnail((900, 900), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(disp)
        dialog._photo = photo

        lbl = ttk.Label(dialog, image=photo)
        lbl.pack(padx=10, pady=10)
        ttk.Label(dialog, text=f"原寸 {img.width}×{img.height}px", foreground="gray").pack()
        ttk.Button(dialog, text="閉じる", command=dialog.destroy).pack(pady=10, ipadx=16, ipady=4)

    def clear_snapshots(self):
        self.snapshot_normal = None
        self.snapshot_blink = None
        self.snapshot_talk = None
        self.lbl_snap_normal.config(text="通常: 未記憶", foreground="gray")
        self.lbl_snap_blink.config(text="目閉じ: 未記憶", foreground="gray")
        self.lbl_snap_talk.config(text="口開け: 未記憶", foreground="gray")
        for lbl in (self.snap_preview_normal, self.snap_preview_blink, self.snap_preview_talk):
            lbl.config(image="")
        self.refresh_preview_image()
        self.check_generate_enabled()

    def check_generate_enabled(self):
        has_normal = self.snapshot_normal is not None
        has_other = self.snapshot_blink is not None or self.snapshot_talk is not None
        has_chara = bool(self.current_chara_id())
        startable = has_normal and has_other and has_chara and (self.psd or self.png_image)
        if startable:
            self.btn_generate.config(state="normal")
            self.btn_generate.focus_set()
        else:
            self.btn_generate.config(state="disabled")
        self._update_gen_status()

    # ==========================================================================
    # 版管理（オリジナルPNGの保管と差異チェック）
    # ==========================================================================
    def originals_dir(self, base=None):
        if base is None:
            base = self.folder_base() if self.current_chara_id() else "unassigned"
        return os.path.join(_app_dir(), base, ORIGINALS_DIR_NAME)

    def original_path(self, mode, base=None):
        return os.path.join(self.originals_dir(base), f"original_{mode}.png")

    def save_originals(self, base=None):
        """生成直後に、状態ごとのマスター画像をオリジナルとして保管"""
        if base is None:
            if not self.current_chara_id():
                return
            base = self.folder_base()
        d = self.originals_dir(base)
        os.makedirs(d, exist_ok=True)
        masters = {
            "normal": self.png_master_normal,
            "blink": self.png_master_blink,
            "talk": self.png_master_talk,
        }
        for mode, img in masters.items():
            if img is None:
                continue
            img.save(self.original_path(mode, base))

    def diff_masters(self):
        """現在のマスター(未決定)とオリジナル保存分を差分比較し status 返す"""
        if not self.current_chara_id():
            return
        for mode in ("normal", "blink", "talk"):
            cur = {"normal": self.snapshot_normal, "blink": self.snapshot_blink, "talk": self.snapshot_talk}[mode]
            orig_path = self.original_path(mode)
            if cur is None:
                self.version_status[mode] = "none"
                continue
            if not os.path.exists(orig_path):
                self.version_status[mode] = "new"   # 未適用（初回）
                continue
            cur_img = self._snapshot_to_image(cur)
            try:
                ori_img = Image.open(orig_path).convert("RGBA")
            except Exception:
                self.version_status[mode] = "new"
                continue
            if self._images_equal(cur_img, ori_img):
                self.version_status[mode] = "applied"
            else:
                self.version_status[mode] = "changed"
        self._update_version_labels()

    def _images_equal(self, a, b):
        if a.size != b.size:
            return False
        return list(a.getdata()) == list(b.getdata())

    def _update_version_labels(self):
        labels = {
            "normal": self.lbl_snap_normal,
            "blink": self.lbl_snap_blink,
            "talk": self.lbl_snap_talk,
        }
        base_text = {
            "normal": "通常",
            "blink": "目閉じ",
            "talk": "口開け",
        }
        for mode, lbl in labels.items():
            st = self.version_status.get(mode, "unknown")
            name = base_text[mode]
            if st == "applied":
                lbl.config(text=f"{name}: 適用済み", foreground="green")
            elif st == "changed":
                lbl.config(text=f"{name}: 変更あり（未適用）", foreground="red")
            elif st == "new":
                lbl.config(text=f"{name}: 未生成/未適用", foreground="orange")
            elif st == "none":
                lbl.config(text=f"{name}: 未記憶", foreground="gray")
            else:
                lbl.config(text=f"{name}: 未記憶", foreground="gray")

    def check_versions_after_load(self):
        # 起動時はスナップショット未設定なので、既存オリジナルがあれば "未適用" のまま
        if not self.characters:
            return
        # 表示のみ更新
        self._update_version_labels()

    def mark_changed_on_new_snapshot(self, mode):
        """スナップショットを変えた時点で、適用済みなら未適用に降格"""
        if self.version_status.get(mode) == "applied":
            self.version_status[mode] = "changed"
        self._update_version_labels()

    # ==========================================================================
    # プレビュー・出力
    # ==========================================================================
    def open_preview_dialog(self):
        if not self.psd and not self.png_image:
            return
        if not self.snapshot_normal:
            messagebox.showwarning("警告", "『通常』の状態を記憶させてから進んでください。")
            return
        if not (self.snapshot_blink or self.snapshot_talk):
            messagebox.showwarning("警告", "『目閉じ』または『口開け』の状態を記憶させてから進んでください。")
            return
        if not self.current_chara_id():
            messagebox.showwarning("警告", "キャラクターを選択または作成してください。")
            return

        dialog = tk.Toplevel(self)
        dialog.title("最終確認プレビュー")
        dialog.geometry("560x700")
        dialog.grab_set()

        img_normal = self._snapshot_to_image(self.snapshot_normal)
        img_blink = self._snapshot_to_image(self.snapshot_blink) if self.snapshot_blink else None
        img_talk = self._snapshot_to_image(self.snapshot_talk) if self.snapshot_talk else None

        thumb_normal = img_normal.copy() if img_normal else None
        thumb_blink = img_blink.copy() if img_blink else None
        thumb_talk = img_talk.copy() if img_talk else None
        if thumb_normal:
            thumb_normal.thumbnail((400, 460), Image.Resampling.LANCZOS)
        if thumb_blink:
            thumb_blink.thumbnail((400, 460), Image.Resampling.LANCZOS)
        if thumb_talk:
            thumb_talk.thumbnail((400, 460), Image.Resampling.LANCZOS)

        self._tk_preview_normal = ImageTk.PhotoImage(thumb_normal) if thumb_normal else None
        self._tk_preview_blink = ImageTk.PhotoImage(thumb_blink) if thumb_blink else None
        self._tk_preview_talk = ImageTk.PhotoImage(thumb_talk) if thumb_talk else None

        info = self.current_chara_info()
        output_name = f"{self.current_chara_id()}_{info['video_track']}_{info['audio_track']}"
        ttk.Label(
            dialog,
            text=f"出力先フォルダ名プレフィックス: {output_name}",
            font=("", 10, "bold")
        ).pack(pady=(10, 0))

        lbl_img = ttk.Label(dialog, image=self._tk_preview_normal)
        lbl_img.pack(pady=10)

        self.preview_step = 0
        self.is_mouth_open = False
        self.is_eye_closed = False

        def update_preview():
            if not dialog.winfo_exists():
                return
            self.preview_step += 1

            # まばたき: 20f周期
            if img_blink and self.preview_step % 20 == 0:
                lbl_img.config(image=self._tk_preview_blink)
            else:
                if self._tk_preview_talk and self.is_mouth_open:
                    lbl_img.config(image=self._tk_preview_normal)
                    self.is_mouth_open = False
                elif self._tk_preview_talk:
                    lbl_img.config(image=self._tk_preview_talk)
                    self.is_mouth_open = True
                else:
                    lbl_img.config(image=self._tk_preview_normal)

            dialog.after(250, update_preview)

        dialog.after(250, update_preview)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=20, padx=20)
        ttk.Button(btn_frame, text="修正する", command=dialog.destroy).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        ttk.Button(btn_frame, text="連番PNGを生成する", command=lambda: [dialog.destroy(), self.execute_png_generation()]).pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=5)

    def generate_masters(self):
        self.png_master_normal = self._snapshot_to_image(self.snapshot_normal)
        self.png_master_blink = self._snapshot_to_image(self.snapshot_blink) if self.snapshot_blink else None
        self.png_master_talk = self._snapshot_to_image(self.snapshot_talk) if self.snapshot_talk else None

        # blink/talk が未設定の場合は normal のコピーで代替（生成は不可だが安全策）
        if self.png_master_blink is None:
            self.png_master_blink = self.png_master_normal.copy()
        if self.png_master_talk is None:
            self.png_master_talk = self.png_master_normal.copy()

    def build_folder_defs(self):
        """variable_block に応じて出力フォルダ定義を返す（10f固定 or 可変）"""
        if not self.variable_block.get():
            return [d for d in FOLDER_DEFS if d["frames"] == 10]
        return list(FOLDER_DEFS)

    def dest_folder(self, state, frames, base=None):
        base = base or self.folder_base()
        return os.path.join(_app_dir(), f"{base}_{state}_{frames}")

    def png_fname(self, state, frame):
        """連番ファイル名: state_0000.png（Resolve側で判別できるよう state を付与）"""
        return f"{state}_{frame:04d}.png"

    def _generation_worker(self, folder_defs, base, report):
        """連番PNG生成の実処理（ワーカースレッドで実行）"""
        master_normal = self.png_master_normal
        master_blink = self.png_master_blink
        master_talk = self.png_master_talk

        done = 0
        total = len(folder_defs)

        def step(folder_name):
            nonlocal done
            done += 1
            report(done, total, folder_name, done == total)

        folders = {}
        for d in folder_defs:
            folder = self.dest_folder(d["state"], d["frames"], base)
            if os.path.exists(folder):
                shutil.rmtree(folder)
            os.makedirs(folder, exist_ok=True)
            folders[d["state"] + "_" + str(d["frames"])] = folder

        # ---- 10f 系 ----
        folder = folders["normal_10"]
        for frame in range(10):
            master_normal.save(os.path.join(folder, self.png_fname("normal", frame)))
        step(os.path.basename(folder))

        folder = folders["blink_10"]
        for frame in range(10):
            if frame < 5:
                master_blink.save(os.path.join(folder, self.png_fname("blink", frame)))
            else:
                master_normal.save(os.path.join(folder, self.png_fname("blink", frame)))
        step(os.path.basename(folder))

        folder = folders["talk_10"]
        for frame in range(10):
            master_talk.save(os.path.join(folder, self.png_fname("talk", frame)))
        step(os.path.basename(folder))

        # ---- 可変ブロック（30f/60f） ----
        if self._use_variable_block:
            # 30f
            folder = folders["normal_30"]
            for frame in range(30):
                master_normal.save(os.path.join(folder, self.png_fname("normal", frame)))
            step(os.path.basename(folder))

            folder = folders["talk_a_30"]  # [T×10, N×10, T×10]
            for frame in range(30):
                if frame < 10 or frame >= 20:
                    master_talk.save(os.path.join(folder, self.png_fname("talk_a", frame)))
                else:
                    master_normal.save(os.path.join(folder, self.png_fname("talk_a", frame)))
            step(os.path.basename(folder))

            folder = folders["talk_b_30"]  # [N×10, T×10, N×10]
            for frame in range(30):
                if 10 <= frame < 20:
                    master_talk.save(os.path.join(folder, self.png_fname("talk_b", frame)))
                else:
                    master_normal.save(os.path.join(folder, self.png_fname("talk_b", frame)))
            step(os.path.basename(folder))

            # 60f
            folder = folders["normal_60"]
            for frame in range(60):
                master_normal.save(os.path.join(folder, self.png_fname("normal", frame)))
            step(os.path.basename(folder))

            folder = folders["talk_a_60"]  # [T,N,T,N,T,N]
            for frame in range(60):
                if (frame // 10) % 2 == 0:
                    master_talk.save(os.path.join(folder, self.png_fname("talk_a", frame)))
                else:
                    master_normal.save(os.path.join(folder, self.png_fname("talk_a", frame)))
            step(os.path.basename(folder))

            folder = folders["talk_b_60"]  # [N,T,N,T,N,T]
            for frame in range(60):
                if (frame // 10) % 2 == 0:
                    master_normal.save(os.path.join(folder, self.png_fname("talk_b", frame)))
                else:
                    master_talk.save(os.path.join(folder, self.png_fname("talk_b", frame)))
            step(os.path.basename(folder))

    def execute_png_generation(self):
        if not self.current_chara_id():
            messagebox.showwarning("警告", "キャラクター名が未設定です。\nキャラクターを選択または作成してください。")
            return

        # キャラクター名を覚えておく（config保存）
        self.save_config()

        # マスター画像の合成（PSD合成は時間がかかるため、進捗ダイアログ内で実施）
        self.generate_masters()
        if self.png_master_normal is None:
            messagebox.showerror("エラー", "『通常』の状態が未設定です。")
            return

        # スレッド安全のため、Tk変数の値をメインスレッドで取得してから渡す
        folder_base = self.folder_base()
        self._use_variable_block = self.variable_block.get()

        folder_defs = self.build_folder_defs()

        # 上書き確認
        existing = [self.dest_folder(d["state"], d["frames"], folder_base) for d in folder_defs if os.path.exists(self.dest_folder(d["state"], d["frames"], folder_base))]
        if existing:
            ans = messagebox.askyesno(
                "上書き警告",
                "既に以下の出力先フォルダが存在します。削除して再生成しますか？\n\n" + "\n".join(existing)
            )
            if not ans:
                return

        total_steps = len(folder_defs)
        prog = ProgressDialog(self, total_steps)

        import queue as _queue
        q = _queue.Queue()

        def run():
            try:
                self._generation_worker(folder_defs, folder_base, lambda done, total, label, is_last: q.put(("progress", done, total, label, is_last)))
                self.save_originals(folder_base)
                q.put(("originals",))
                q.put(("done",))
            except Exception as e:
                q.put(("error", e))

        import threading as _threading
        worker = _threading.Thread(target=run, daemon=True)
        worker.start()

        def poll():
            try:
                msg = q.get_nowait()
            except _queue.Empty:
                self.after(80, poll)
                return

            if msg[0] == "progress":
                _, done, total, label, _ = msg
                prog.set_status(f"生成中… {label}")
                prog.set_progress(done)
                self.after(80, poll)
            elif msg[0] == "originals":
                self.version_status = {"normal": "applied", "blink": "applied", "talk": "applied"}
                prog.set_status("版管理用オリジナル画像を保存中…")
                self.after(80, poll)
            elif msg[0] == "error":
                prog.destroy()
                self.save_config()
                messagebox.showerror("エラー", f"生成中にエラーが発生しました:\n{msg[1]}")
            elif msg[0] == "done":
                prog.set_status("完了！")
                prog.set_progress(total_steps)
                self.after(150, finish)
            else:
                self.after(80, poll)

        def finish():
            prog.destroy()
            self._update_version_labels()
            self.save_config()
            messagebox.showinfo("成功", "すべての連番PNGの生成が完了しました！")
            os.startfile(_app_dir())
            if self.show_tutorial.get():
                TutorialDialog(self)

        poll()

    # ==========================================================================
    # Resolveコピー
    # ==========================================================================
    def copy_script_to_resolve(self):
        self.ensure_local_script()
        current_script_path, remote = self.script_paths()
        if not os.path.exists(current_script_path):
            messagebox.showerror("エラー", f"元スクリプト '{RESOLVE_SCRIPT_NAME}' が見つかりません。")
            return
        try:
            os.makedirs(os.path.dirname(remote), exist_ok=True)
            shutil.copy2(current_script_path, remote)
            messagebox.showinfo("成功", "Resolveにスクリプトをコピーしました。")
        except Exception as e:
            messagebox.showerror("エラー", f"コピー失敗: {e}")

    # ==========================================================================
    # 設定の保存・読込
    # ==========================================================================
    def load_config(self):
        path = _config_path()
        if not os.path.exists(path) and getattr(sys, "frozen", False):
            # exe初回起動時: 内包した既定設定を exe 横に展開する
            try:
                base = getattr(sys, "_MEIPASS", None)
                if base:
                    bundled = os.path.join(base, "config.default.json")
                    if os.path.exists(bundled):
                        shutil.copy2(bundled, path)
            except Exception as e:
                self.log("error", f"既定設定の展開失敗: {e}")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.fps.set(data.get("fps", 60))
                    self.blink_min.set(data.get("blink_min", 5.0))
                    self.blink_max.set(data.get("blink_max", 10.0))
                    self.show_tutorial.set(data.get("show_tutorial", True))
                    self.variable_block.set(data.get("variable_block", True))
                    self.characters = data.get("characters", {})
                    cur = data.get("current_character", "")
                    if cur and cur in self.characters:
                        self.current_character.set(cur)
            except Exception as e:
                self.log("error", f"設定読込失敗: {e}")

    def save_config(self):
        config_data = {
            "fps": self.fps.get(),
            "blink_min": self.blink_min.get(),
            "blink_max": self.blink_max.get(),
            "show_tutorial": self.show_tutorial.get(),
            "variable_block": self.variable_block.get(),
            "current_character": self.current_character.get(),
            "characters": self.characters,
        }
        try:
            with open(_config_path(), "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log("error", f"設定保存失敗: {e}")


if __name__ == "__main__":
    app = App()
    app.mainloop()
