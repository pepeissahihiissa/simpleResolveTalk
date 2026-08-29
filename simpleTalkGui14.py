import os
import sys
import json
import random
import shutil
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
from psd_tools import PSDImage

CONFIG_FILE = "config.json"
RESOLVE_SCRIPT_DIR = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility"
RESOLVE_SCRIPT_NAME = "character_lip_sync.py"

DIR_NORMAL = "normal_seq"
DIR_TALK   = "talk_seq"
DIR_BLINK  = "blink_seq"

class TutorialDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("DaVinci Resolve 連携手順（読込・配置ガイド）")
        self.geometry("650x580")
        self.resizable(False, False)
        self.grab_set()

        # スライドのデータ定義
        self.slides = [
            {
                "title": "1. 連番PNGの出力が完了しました",
                "text": "現在のフォルダに以下の3つのフォルダ（連番PNG）が生成されました。\n\n"
                        "・「 normal_seq 」 (通常時)\n"
                        "・「 blink_seq 」 (まばたき)\n"
                        "・「 talk_seq 」 (口パク)\n\n"
                        "これらをDaVinci Resolveに読み込ませる準備を行います。",
                "image_path": "step1.png"
            },
            {
                "title": "2. Resolveへのシーケンス読み込み設定",
                "text": "1. DaVinci Resolveの「メディア」タブを開きます。\n"
                        "2. 画面左上「メディアストレージ」の右上にある「…（三点リーダ）」をクリックします。\n"
                        "3.「フレーム表示モード」 ＞ 「シーケンス」を選択します。\n"
                        "4. 出力された3つのフォルダを、下の「メディアプール」へ順にドラッグ＆ドロップします。\n\n"
                        "※これにより、各フォルダが「1本の動画素材（シーケンス素材）」としてResolveに認識されます。",
                "image_path": "step2.png"
            },
            {
                "title": "3. タイムライン配置と基準位置の設定",
                "text": "1. 読み込んだ「 normal_seq 」（シーケンス素材）を、タイムラインの\n"
                        "   ビデオトラック2 (V2) の最初に配置します。\n"
                        "2. インスペクタでキャラクターの「ズーム」や「位置（上下左右）」を調整します。\n\n"
                        "※後ほど実行する自動化マクロ（スクリプト）は、このV2に置かれた素材の座標情報を\n"
                        "  「ベース（基準）」として口パクや表情バリエーションを自動配置します。",
                "image_path": "step3.png"
            }
        ]

        self.current_index = 0
        self.skip_var = tk.BooleanVar(value=not parent.show_tutorial.get())

        self.create_widgets()
        self.show_slide(0)

    def create_widgets(self):
        # メインコンテンツエリア
        self.content_frame = ttk.Frame(self, padding=20)
        self.content_frame.pack(fill=tk.BOTH, expand=True)

        # タイトル
        self.lbl_title = ttk.Label(self.content_frame, text="", font=("", 14, "bold"))
        self.lbl_title.pack(anchor=tk.W, pady=(0, 10))

        # 画像表示エリア（固定サイズ枠）
        self.img_frame = ttk.Frame(self.content_frame, width=580, height=240, relief="solid", borderwidth=1)
        self.img_frame.pack_propagate(False)
        self.img_frame.pack(pady=(0, 15))
        
        self.lbl_image = ttk.Label(self.img_frame, anchor="center")
        self.lbl_image.pack(fill=tk.BOTH, expand=True)

        # 説明文
        self.lbl_text = ttk.Label(self.content_frame, text="", font=("", 10), justify=tk.LEFT, wraplength=560)
        self.lbl_text.pack(fill=tk.BOTH, expand=True, anchor=tk.NW)

        # ボトムコントロールエリア
        self.bottom_frame = ttk.Frame(self, padding=15)
        self.bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)

        # 次回から表示しないチェックボックス
        self.chk_skip = ttk.Checkbutton(self.bottom_frame, text="次回からこのガイドを表示しない", variable=self.skip_var, command=self.on_skip_toggle)
        self.chk_skip.pack(side=tk.LEFT)

        # ナビゲーションボタン
        self.btn_next = ttk.Button(self.bottom_frame, text="次へ ＞", command=self.next_slide)
        self.btn_next.pack(side=tk.RIGHT, padx=5)

        self.btn_prev = ttk.Button(self.bottom_frame, text="＜ 前へ", command=self.prev_slide)
        self.btn_prev.pack(side=tk.RIGHT, padx=5)

        # ページ表示
        self.lbl_page = ttk.Label(self.bottom_frame, text="", font=("", 10))
        self.lbl_page.pack(side=tk.RIGHT, padx=15)

    def show_slide(self, index):
        slide = self.slides[index]
        self.lbl_title.config(text=slide["title"])
        self.lbl_text.config(text=slide["text"])
        self.lbl_page.config(text=f"{index + 1} / {len(self.slides)}")

        # 画像の読み込みと表示（フォールバック付き）
        if os.path.exists(slide["image_path"]):
            try:
                img = Image.open(slide["image_path"])
                img.thumbnail((578, 238), Image.Resampling.LANCZOS)
                self.tk_img = ImageTk.PhotoImage(img)
                self.lbl_image.config(image=self.tk_img, text="")
            except Exception:
                self.lbl_image.config(image="", text="[ 画像の読み込みに失敗しました ]")
        else:
            # 画像がない場合はダミーテキストを表示して枠を維持
            self.lbl_image.config(image="", text="[ 関連スクリーンショットの配置エリア ]\n(※同ディレクトリに step1.png ~ step3.png があれば表示されます)")

        # ボタンの有効・無効、テキスト切り替え制御
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
        # 親クラスのフラグを反転させて設定を保存
        self.parent.show_tutorial.set(not self.skip_var.get())
        self.parent.save_config()


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("キャラ口パク・まばたき自動化ツール (v1.9)")
        self.geometry("1200x750")
        
        # PSD・レイヤー状態管理
        self.psd = None
        self.layer_flat_map = {}  
        self.layer_vis_states = {} 
        self.layer_is_radio = {}   
        
        self.snapshot_normal = None
        self.snapshot_blink = None
        self.snapshot_talk = None

        self.fps = tk.IntVar(value=60)
        self.blink_min = tk.DoubleVar(value=5.0)
        self.blink_max = tk.DoubleVar(value=10.0)
        self.psd_path = tk.StringVar()
        self.show_tutorial = tk.BooleanVar(value=True)  # チュートリアル表示フラグ
        self.variable_block = tk.BooleanVar(value=True)  # 可変ブロックサイズ

        # PNG・JPEG状態管理
        self.png_path = tk.StringVar()
        self.png_image = None
        self.current_mode = "psd"  # "psd" or "png"

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

        self.create_widgets()
        self.load_config()

    def log(self, level, message):
        print(f"[{level.upper()}] {message}")

    def create_widgets(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_timeline = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(self.tab_timeline, text=" タイムライン設定 ")
        self.build_timeline_tab()

        self.tab_psd = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_psd, text=" 立ち絵設定 ")
        self.build_psd_tab()

    def build_timeline_tab(self):
        setup_frame = ttk.LabelFrame(self.tab_timeline, text=" 1. システム連携 ", padding=10)
        setup_frame.pack(fill=tk.X, pady=5)
        ttk.Button(setup_frame, text="DaVinci Resolveへスクリプトをコピー", command=self.copy_script_to_resolve).pack(fill=tk.X)

        param_frame = ttk.LabelFrame(self.tab_timeline, text=" 2. アニメーションパラメータ調整 ", padding=10)
        param_frame.pack(fill=tk.X, pady=10)
        ttk.Label(param_frame, text="ベースFPS:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(param_frame, textvariable=self.fps, width=10).grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Label(param_frame, text="まばたき最小間隔 (秒):").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(param_frame, textvariable=self.blink_min, width=10).grid(row=1, column=1, sticky=tk.W, padx=5)
        ttk.Label(param_frame, text="まばたき最大間隔 (秒):").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(param_frame, textvariable=self.blink_max, width=10).grid(row=2, column=1, sticky=tk.W, padx=5)
        ttk.Checkbutton(param_frame, text="可変ブロックサイズを使用（10f/30f/60f）", variable=self.variable_block).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=10)

    def build_psd_tab(self):
        file_frame = ttk.Frame(self.tab_psd)
        file_frame.pack(fill=tk.X, pady=(0, 5))
        # PNG/JPEG読み込み行
        png_row = ttk.Frame(file_frame)
        png_row.pack(fill=tk.X, pady=(0, 3))
        ttk.Entry(png_row, textvariable=self.png_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(png_row, text="PNG/JPEG読込", command=self.load_png).pack(side=tk.RIGHT)
        # PSD読み込み行
        psd_row = ttk.Frame(file_frame)
        psd_row.pack(fill=tk.X)
        ttk.Entry(psd_row, textvariable=self.psd_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(psd_row, text="PSD読込", command=self.load_psd).pack(side=tk.RIGHT)

        main_paned = ttk.PanedWindow(self.tab_psd, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True)

        self.layer_tree_frame = ttk.LabelFrame(main_paned, text=" レイヤー構造（アイコンをクリックしてON/OFF） ")
        main_paned.add(self.layer_tree_frame, weight=4)

        self.tree = ttk.Treeview(self.layer_tree_frame, selectmode="browse", show="tree")
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        self.tree_scrollbar = ttk.Scrollbar(self.layer_tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree_scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.tree.configure(yscrollcommand=self.tree_scrollbar.set)
        
        self.tree.bind("<Button-1>", self.on_tree_click)

        # PNGモード用ラベル（初期は非表示）
        self.png_mode_label = ttk.Label(self.layer_tree_frame, text="PNG/JPEGモード：プレビューのみ", anchor="center", font=("", 11))

        center_frame = ttk.LabelFrame(main_paned, text=" リアルタイムプレビュー ")
        main_paned.add(center_frame, weight=5)
        
        self.lbl_preview = ttk.Label(center_frame, anchor="center")
        self.lbl_preview.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        right_frame = ttk.LabelFrame(main_paned, text=" 状態登録と出力 ", padding=10)
        main_paned.add(right_frame, weight=3)

        ttk.Button(right_frame, text="現在の見た目を【通常】として記憶", command=lambda: self.save_snapshot("normal")).pack(fill=tk.X, pady=5)
        self.lbl_snap_normal = ttk.Label(right_frame, text="通常: 未記憶", foreground="gray")
        self.lbl_snap_normal.pack(fill=tk.X, pady=(0, 15))

        ttk.Button(right_frame, text="現在の見た目を【目閉じ】として記憶", command=lambda: self.save_snapshot("blink")).pack(fill=tk.X, pady=5)
        self.lbl_snap_blink = ttk.Label(right_frame, text="目閉じ: 未記憶", foreground="gray")
        self.lbl_snap_blink.pack(fill=tk.X, pady=(0, 15))

        ttk.Button(right_frame, text="現在の見た目を【口開け】として記憶", command=lambda: self.save_snapshot("talk")).pack(fill=tk.X, pady=5)
        self.lbl_snap_talk = ttk.Label(right_frame, text="口開け: 未記憶", foreground="gray")
        self.lbl_snap_talk.pack(fill=tk.X, pady=(0, 15))

        ttk.Button(right_frame, text="アニメーション確認 ＆ 連番生成", command=self.open_preview_dialog).pack(fill=tk.X, side=tk.BOTTOM, ipady=8)
        ttk.Button(right_frame, text="タイミングJSONから連番生成（新方式）", command=self.generate_sequence_from_timing).pack(fill=tk.X, side=tk.BOTTOM, ipady=8, pady=(5, 0))

    # ------------------------------------------------------------------------------
    # 処理ロジック
    # ------------------------------------------------------------------------------
    def load_png(self):
        file_path = filedialog.askopenfilename(title="画像ファイルを選択", filetypes=[("画像ファイル", "*.png *.jpg *.jpeg *.bmp *.gif"), ("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg")])
        if not file_path:
            return
        self.png_path.set(file_path)
        self.log("info", f"画像の読み込みを開始します: {file_path}")
        try:
            self.png_image = Image.open(file_path).convert("RGBA")
            self.current_mode = "png"
            self.layer_tree_frame.config(text=" PNG/JPEGモード（プレビューのみ） ")
            self.tree.pack_forget()
            self.tree_scrollbar.pack_forget()
            self.png_mode_label.pack(fill=tk.BOTH, expand=True)
            self.refresh_preview_image()
            self.log("info", f"画像を読み込みました: {file_path}")
            messagebox.showinfo("完了", "画像ファイルを読み込みました。\n右側のボタンで各状態として記憶してください。")
        except Exception as e:
            self.log("error", f"画像の解析中にエラーが発生しました: {e}")
            messagebox.showerror("エラー", f"画像を開けませんでした: {e}")

    def load_psd(self):
        file_path = filedialog.askopenfilename(title="PSDファイルを選択", filetypes=[("Photoshop Files", "*.psd")])
        if not file_path:
            return
        
        old_psd_path = self.psd_path.get()
        self.psd_path.set(file_path)
        if old_psd_path != file_path:
            self.clear_snapshots()
        self.current_mode = "psd"
        self.layer_tree_frame.config(text=" レイヤー構造（アイコンをクリックしてON/OFF） ")
        self.png_mode_label.pack_forget()
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        self.tree_scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.log("info", f"PSDのパースを開始します: {file_path}")
        
        try:
            self.psd = PSDImage.open(file_path)
            
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
            
            self.log("info", f"ツリー構築完了。総レイヤー(ノード)数: {len(self.layer_flat_map)}")
            self.refresh_preview_image()
            messagebox.showinfo("完了", "PSDファイルを読み込みました。")
            
            visible_count = 0
            for node_id, layer in self.layer_flat_map.items():
                try:
                    if layer.is_visible():
                        visible_count += 1
                except:
                    pass
            self.log("debug", f"初期状態の可視実ノード数: {visible_count}")

        except Exception as e:
            self.log("error", f"PSDの解析中に致命的なエラーが発生しました: {e}")

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

    # ------------------------------------------------------------------------------
    # 📌 画像合成
    # ------------------------------------------------------------------------------
    def generate_composite(self, custom_states=None):
        if self.current_mode == "png":
            if isinstance(custom_states, Image.Image):
                return custom_states.copy()
            return self.png_image.copy() if self.png_image else None

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
        img = self.generate_composite()
        if img:
            self.update_idletasks()
            w = max(400, self.lbl_preview.winfo_width())
            h = max(500, self.lbl_preview.winfo_height())
            
            img.thumbnail((w, h), Image.Resampling.LANCZOS)
            self.tk_preview_img = ImageTk.PhotoImage(img)
            self.lbl_preview.config(image=self.tk_preview_img)
            self.log("info", f"画面上のプレビューをリフレッシュしました。")
        else:
            self.log("warn", "プレビュー用画像の生成に失敗しました。")

    # ------------------------------------------------------------------------------
    # 共通処理
    # ------------------------------------------------------------------------------
    def save_snapshot(self, mode):
        if not self.psd and not self.png_image:
            return
        if self.current_mode == "png":
            if self.png_image is None:
                return
            current_snapshot = self.png_image.copy()
        else:
            current_snapshot = dict(self.layer_vis_states)
        if mode == "normal":
            self.snapshot_normal = current_snapshot
            self.lbl_snap_normal.config(text="通常: 記憶済み (OK)", foreground="green")
        elif mode == "blink":
            self.snapshot_blink = current_snapshot
            self.lbl_snap_blink.config(text="目閉じ: 記憶済み (OK)", foreground="green")
        elif mode == "talk":
            self.snapshot_talk = current_snapshot
            self.lbl_snap_talk.config(text="口開け: 記憶済み (OK)", foreground="green")
        self.log("info", f"【スナップショット】状態 '{mode}' を保存しました。")

    def clear_snapshots(self):
        self.snapshot_normal = None
        self.snapshot_blink = None
        self.snapshot_talk = None
        self.lbl_snap_normal.config(text="通常: 未記憶", foreground="gray")
        self.lbl_snap_blink.config(text="目閉じ: 未記憶", foreground="gray")
        self.lbl_snap_talk.config(text="口開け: 未記憶", foreground="gray")

    def open_preview_dialog(self):
        if not self.psd and not self.png_image:
            return
        if not (self.snapshot_normal and self.snapshot_blink and self.snapshot_talk):
            messagebox.showwarning("警告", "通常、目閉じ、口開けの3つの状態をすべて記憶させてから進んでください。")
            return

        dialog = tk.Toplevel(self)
        dialog.title("最終確認プレビュー")
        dialog.geometry("500x650")
        dialog.grab_set()

        img_normal = self.generate_composite(self.snapshot_normal)
        img_blink  = self.generate_composite(self.snapshot_blink)
        img_talk   = self.generate_composite(self.snapshot_talk)
        
        img_normal.thumbnail((400, 500), Image.Resampling.LANCZOS)
        img_blink.thumbnail((400, 500), Image.Resampling.LANCZOS)
        img_talk.thumbnail((400, 500), Image.Resampling.LANCZOS)

        tk_normal = ImageTk.PhotoImage(img_normal)
        tk_blink  = ImageTk.PhotoImage(img_blink)
        tk_talk   = ImageTk.PhotoImage(img_talk)

        lbl_img = ttk.Label(dialog, image=tk_normal)
        lbl_img.pack(pady=20)

        self.preview_step = 0
        self.is_mouth_open = False

        def update_preview():
            if not dialog.winfo_exists(): return
            
            self.preview_step += 1
            
            if self.preview_step % 20 == 0:
                lbl_img.config(image=tk_blink)
            else:
                if self.is_mouth_open:
                    lbl_img.config(image=tk_normal)
                    self.is_mouth_open = False
                else:
                    lbl_img.config(image=tk_talk)
                    self.is_mouth_open = True
                    
            dialog.after(250, update_preview)

        dialog.after(250, update_preview)
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=20, padx=20)
        ttk.Button(btn_frame, text="修正する", command=dialog.destroy).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        ttk.Button(btn_frame, text="連番PNGを生成する", command=lambda: [dialog.destroy(), self.execute_png_generation()]).pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=5)

    def execute_png_generation(self):
        dirs_30f = ["normal_30f", "talk_30f_a", "talk_30f_b", "blink_30f"]
        dirs_60f = ["normal_60f", "talk_60f_a", "talk_60f_b", "blink_60f"]
        all_dirs = [DIR_NORMAL, DIR_BLINK, DIR_TALK]
        if self.variable_block.get():
            all_dirs += dirs_30f
            all_dirs += dirs_60f

        existing_dirs = [d for d in all_dirs if os.path.exists(d)]
        if existing_dirs:
            ans = messagebox.askyesno("上書き警告", "既に出力先フォルダが存在します。削除して再生成しますか？\n\n" + "\n".join(existing_dirs))
            if not ans: return

        for d in all_dirs:
            if os.path.exists(d): shutil.rmtree(d)
            os.makedirs(d, exist_ok=True)

        master_normal = self.generate_composite(self.snapshot_normal)
        master_blink  = self.generate_composite(self.snapshot_blink)
        master_talk   = self.generate_composite(self.snapshot_talk)

        # 10fブロック（従来方式）
        for frame in range(10):
            master_normal.save(os.path.join(DIR_NORMAL, f"normal_{frame:04d}.png"))
            master_talk.save(os.path.join(DIR_TALK, f"talk_{frame:04d}.png"))
            if frame < 5:
                master_blink.save(os.path.join(DIR_BLINK, f"blink_{frame:04d}.png"))
            else:
                master_normal.save(os.path.join(DIR_BLINK, f"blink_{frame:04d}.png"))

        # 30fブロック（可変ブロック方式）
        if self.variable_block.get():
            for frame in range(30):
                master_normal.save(os.path.join("normal_30f", f"normal_30f_{frame:04d}.png"))
                if frame < 5:
                    master_blink.save(os.path.join("blink_30f", f"blink_30f_{frame:04d}.png"))
                else:
                    master_normal.save(os.path.join("blink_30f", f"blink_30f_{frame:04d}.png"))
                # talk_30f_a: [T×10, N×10, T×10]
                # talk_30f_b: [N×10, T×10, N×10]
                if frame < 10:
                    master_talk.save(os.path.join("talk_30f_a", f"talk_30f_a_{frame:04d}.png"))
                    master_normal.save(os.path.join("talk_30f_b", f"talk_30f_b_{frame:04d}.png"))
                elif frame < 20:
                    master_normal.save(os.path.join("talk_30f_a", f"talk_30f_a_{frame:04d}.png"))
                    master_talk.save(os.path.join("talk_30f_b", f"talk_30f_b_{frame:04d}.png"))
                else:
                    master_talk.save(os.path.join("talk_30f_a", f"talk_30f_a_{frame:04d}.png"))
                    master_normal.save(os.path.join("talk_30f_b", f"talk_30f_b_{frame:04d}.png"))

            # 60fブロック（可変ブロック方式）
            for frame in range(60):
                master_normal.save(os.path.join("normal_60f", f"normal_60f_{frame:04d}.png"))
                if frame < 5:
                    master_blink.save(os.path.join("blink_60f", f"blink_60f_{frame:04d}.png"))
                else:
                    master_normal.save(os.path.join("blink_60f", f"blink_60f_{frame:04d}.png"))
                # talk_60f_a: [T×10, N×10, T×10, N×10, T×10, N×10]
                # talk_60f_b: [N×10, T×10, N×10, T×10, N×10, T×10]
                if (frame // 10) % 2 == 0:
                    master_talk.save(os.path.join("talk_60f_a", f"talk_60f_a_{frame:04d}.png"))
                    master_normal.save(os.path.join("talk_60f_b", f"talk_60f_b_{frame:04d}.png"))
                else:
                    master_normal.save(os.path.join("talk_60f_a", f"talk_60f_a_{frame:04d}.png"))
                    master_talk.save(os.path.join("talk_60f_b", f"talk_60f_b_{frame:04d}.png"))

        self.save_config()
        messagebox.showinfo("成功", "すべての連番PNGの生成が完了しました！")
        os.startfile(os.getcwd())

        # スキップ設定になっていなければチュートリアルを起動
        if self.show_tutorial.get():
            TutorialDialog(self)

    def generate_sequence_from_timing(self):
        if not (self.snapshot_normal and self.snapshot_blink and self.snapshot_talk):
            messagebox.showwarning("警告", "通常、目閉じ、口開けの3つの状態をすべて記憶させてから進んでください。")
            return

        json_path = filedialog.askopenfilename(
            title="タイミングJSONファイルを選択",
            filetypes=[("JSON", "*.json")]
        )
        if not json_path:
            return

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                timing = json.load(f)
        except Exception as e:
            messagebox.showerror("エラー", f"JSONの読み込みに失敗しました: {e}")
            return

        total_frames = timing.get("total_frames", 0)
        segments = timing.get("segments", [])
        timing_fps = timing.get("fps", self.fps.get())
        if total_frames <= 0 or not segments:
            messagebox.showerror("エラー", "JSONに有効なフレーム情報がありません。")
            return

        output_dir = "timing_output"
        if os.path.exists(output_dir):
            ans = messagebox.askyesno("上書き警告", f"出力先フォルダ '{output_dir}' は既に存在します。削除して再生成しますか？")
            if not ans:
                return
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # 事前合成画像を生成
        master_normal = self.generate_composite(self.snapshot_normal)
        master_blink = self.generate_composite(self.snapshot_blink)
        master_talk = self.generate_composite(self.snapshot_talk)
        master_images = {"normal": master_normal, "blink": master_blink, "talk": master_talk}

        if not all(master_images.values()):
            messagebox.showerror("エラー", "画像の合成に失敗しました。")
            return

        BLOCK_FRAMES = 10
        n_blocks = (total_frames + BLOCK_FRAMES - 1) // BLOCK_FRAMES

        # ブロック単位の状態配列（AIUEO拡張時はここに"a"/"i"/"u"/"e"/"o" が入る）
        block_states = ["normal"] * n_blocks

        # セグメントからブロック状態を構築
        for seg in segments:
            seg_start = seg["start"]
            seg_end = seg["end"]
            seg_state = seg.get("state", "normal")
            first_block = seg_start // BLOCK_FRAMES
            last_block = min((seg_end - 1) // BLOCK_FRAMES, n_blocks - 1)

            if seg_state == "talk":
                # talk区間: 10fごとに talk/normal を交互
                is_last_talk = False
                for bi in range(first_block, last_block + 1):
                    if is_last_talk:
                        block_states[bi] = "normal"
                        is_last_talk = False
                    else:
                        block_states[bi] = "talk"
                        is_last_talk = True
            else:
                # talk以外 (normal / 将来のAIUEO) : そのまま設定
                for bi in range(first_block, last_block + 1):
                    block_states[bi] = seg_state

        # まばたき: normal ブロック上にランダム配置（フレーム番号基準の決定論的シード）
        min_blink_frames = int(self.blink_min.get() * timing_fps)
        max_blink_frames = int(self.blink_max.get() * timing_fps)
        next_blink_frame = (min_blink_frames + max_blink_frames) // 2
        for bi in range(n_blocks):
            block_start = bi * BLOCK_FRAMES
            if block_states[bi] == "normal" and block_start >= next_blink_frame:
                block_states[bi] = "blink"
                r = ((bi * 7 + 13) % (max_blink_frames - min_blink_frames + 1)) + min_blink_frames
                next_blink_frame = block_start + r

        # 連番PNG出力
        total_saved = 0
        start_gen = time.time()
        log_interval = max(1, total_frames // 100)

        for bi in range(n_blocks):
            state = block_states[bi]
            img = master_images.get(state, master_normal)

            for fi in range(BLOCK_FRAMES):
                frame_index = bi * BLOCK_FRAMES + fi
                if frame_index >= total_frames:
                    break
                img.save(os.path.join(output_dir, f"output_{frame_index:06d}.png"))
                total_saved += 1

            if total_saved % log_interval == 0:
                pct = 100 * total_saved // total_frames
                self.log("info", f"連番PNG生成: {pct}% ({total_saved}/{total_frames})")

        elapsed = time.time() - start_gen
        self.log("info", f"連番PNG生成完了: {total_saved}フレーム、{elapsed:.1f}秒")

        self.save_config()
        messagebox.showinfo("成功", f"連番PNGの生成が完了しました！（{total_frames}フレーム / {elapsed:.1f}秒）\n出力先: {os.path.abspath(output_dir)}")
        os.startfile(os.path.abspath(output_dir))

    def copy_script_to_resolve(self):
        current_script_path = os.path.join(os.getcwd(), RESOLVE_SCRIPT_NAME)
        if not os.path.exists(current_script_path):
            messagebox.showerror("エラー", f"元スクリプト '{RESOLVE_SCRIPT_NAME}' が見つかりません。")
            return
        try:
            os.makedirs(RESOLVE_SCRIPT_DIR, exist_ok=True)
            shutil.copy2(current_script_path, os.path.join(RESOLVE_SCRIPT_DIR, RESOLVE_SCRIPT_NAME))
            messagebox.showinfo("成功", "Resolveにスクリプトをコピーしました。")
        except Exception as e:
            messagebox.showerror("エラー", f"コピー失敗: {e}")

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.fps.set(data.get("fps", 60))
                    self.blink_min.set(data.get("blink_min", 5.0))
                    self.blink_max.set(data.get("blink_max", 10.0))
                    self.show_tutorial.set(data.get("show_tutorial", True))
                    self.variable_block.set(data.get("variable_block", True))
            except Exception as e: print(e)

    def save_config(self):
        config_data = {
            "fps": self.fps.get(), 
            "blink_min": self.blink_min.get(), 
            "blink_max": self.blink_max.get(),
            "show_tutorial": self.show_tutorial.get(),
            "variable_block": self.variable_block.get()
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    app = App()
    app.mainloop()