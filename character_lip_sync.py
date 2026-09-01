import os
import sys
import random
import re
import time
import shutil
import tempfile

# ==============================================================================
# ユーザー設定
# ==============================================================================
BLOCK_FRAMES = 10  # 1ブロックの基本フレーム数 (10f)
STOP_FLAG_FILE = "stop_flag.txt"  # このファイルを作成すると安全停止
STOP_CHECK_PATHS = None  # 起動時に決定

# --- 可変ブロックサイズ設定 ---
USE_VARIABLE_BLOCK = True  # True: 10f/30f/60fを使い分け / False: 従来の10f固定
# 60f→30f→10fの順にフォールバック（高サイズの素材がない場合は自動的に低サイズに）
SKIP_OCCUPIED_RANGES = True  # True: 配置先トラックに既存クリップがある区間をスキップ

# --- 変形適用モード ---
# 0 = SKIP: SetPropertyしない（最速、事前変形済み前提）
# 1 = APPLY_AFTER: 配置後にSetProperty（現状のFalse相当）
# 2 = PRE_TRANSFORM: Fusionで事前変形 → 配置（SetPropertyなし）
TRANSFORM_MODE = 0

# --- 基準変形パラメータ（トラック2最初のクリップから取得、または手動指定） ---
# Pan/Tilt: 位置, ZoomX/ZoomY: ズーム, FlipX/FlipY: 反転, Rotation: 回転(度)
# CropLeft/Right/Top/Bottom: クロップ(0.0-1.0), Opacity: 不透明度(0.0-1.0), CompositeMode: 合成モード
TRANSFORM_PARAMS = {
    "Pan": 0.0,
    "Tilt": 0.0,
    "ZoomX": 1.0,
    "ZoomY": 1.0,
    "FlipX": 1.0,   # -1.0 で左右反転, 1.0 で通常
    "FlipY": 1.0,   # -1.0 で上下反転, 1.0 で通常
    "Rotation": 0.0,  # 回転角度(度), 0.0 でなし
    "CropLeft": 0.0,
    "CropRight": 0.0,
    "CropTop": 0.0,
    "CropBottom": 0.0,
    "Opacity": 1.0,
    "CompositeMode": 0,
}

# メディアプール内での連番PNGの登録名（10fブロック）
NORMAL_CLIP_NAME = "normal_[0000-0009].png"
TALK_CLIP_NAME   = "talk_[0000-0009].png"
BLINK_CLIP_NAME  = "blink_[0000-0009].png"

# 30fブロック用（可変ブロックモード）
NORMAL_30F_CLIP_NAME = "normal_30f_[0000-0029].png"
TALK_30F_A_CLIP_NAME = "talk_30f_a_[0000-0029].png"
TALK_30F_B_CLIP_NAME = "talk_30f_b_[0000-0029].png"
BLINK_30F_CLIP_NAME  = "blink_30f_[0000-0029].png"

# 60fブロック用（可変ブロックモード）
NORMAL_60F_CLIP_NAME = "normal_60f_[0000-0059].png"
TALK_60F_A_CLIP_NAME = "talk_60f_a_[0000-0059].png"
TALK_60F_B_CLIP_NAME = "talk_60f_b_[0000-0059].png"
BLINK_60F_CLIP_NAME  = "blink_60f_[0000-0059].png"

VIDEO_TRACK = 2  # キャラクターを配置するトラック
AUDIO_TRACK = 1  # セリフが配置されているトラック

# ==============================================================================
# 新フォルダ形式モード（simpleTalkGui.py の連番PNG書き出しに対応）
# ------------------------------------------------------------------------------
# 従来方式（上記の固定クリップ名）は無傷のまま、このフラグで新方式に切り替えます。
# 新方式は「キャラ名_ビデオトラック_オーディオトラック_状態_フレーム数」形式の
# クリップ名をメディアプールから自動検索し、クリップ名からトラック番号を読み取って
# 複数キャラを自動配置します。また、まばたき（blink）は10fのみ（新GUIは30f/60fを
# 生成しないため）。
# ==============================================================================
USE_NEW_FOLDER_FORMAT = True  # True: 新方式（自動検索・複数キャラ対応）/ False: 従来方式

# 新方式での配置基準変形の取得と適用方法
#   base: 各キャラの配置先ビデオトラックに既に配置されている先頭クリップから取得
#   apply: 0=SKIP(SetPropertyしない) / 1=APPLY_AFTER(配置後にSetProperty) / 2=PRE_TRANSFORM
NEW_TRANSFORM_MODE = 1  # 既定は1（配置後に変形を適用）

# 連番PNGを1ブロックとして連続配置する際のバッファサイズ
NEW_BATCH_SIZE = 50

# ==============================================================================
# ユーティリティ関数
# ==============================================================================
def find_clip(folder, clip_name):
    """メディアプール内を再帰的に検索して指定された名前のクリップを返す"""
    for clip in folder.GetClipList():
        if clip.GetName() == clip_name:
            return clip
    for subfolder in folder.GetSubFolderList():
        result = find_clip(subfolder, clip_name)
        if result:
            return result
    return None

def clear_track_clips(timeline, track_type, track_index):
    """指定されたトラック上の既存クリップをすべて削除する（上書きバグ防止用）"""
    items = timeline.GetItemListInTrack(track_type, track_index)
    if items:
        # APIの仕様上、DeleteClipsにはリストで渡す必要があります
        timeline.DeleteClips(items)
        print(f"[INFO] トラック {track_type} {track_index} の既存クリップをクリアしました。")

def parse_timecode(tc_str, fps):
    """'01:00:00:00' → フレーム数"""
    if not tc_str or not isinstance(tc_str, str):
        return 0
    parts = tc_str.split(":")
    if len(parts) == 4:
        try:
            return int(parts[0]) * 3600 * fps + int(parts[1]) * 60 * fps + int(parts[2]) * fps + int(parts[3])
        except ValueError:
            return 0
    return 0

def detect_start_offset(timeline, project, fps=60):
    """タイムラインの開始タイムコードを自動検出"""
    try:
        tc = timeline.GetStartTimecode()
        offset = parse_timecode(tc, fps)
        print(f"[INFO] 開始タイムコード: '{tc}' → {offset}f (fps={fps})")
        return offset
    except Exception as e:
        print(f"[WARN] 開始タイムコード取得失敗: {e}")
        try:
            min_frame = None
            for ti in range(1, timeline.GetTrackCount("video") + 1):
                for item in timeline.GetItemListInTrack("video", ti):
                    s = item.GetStart()
                    if min_frame is None or s < min_frame:
                        min_frame = s
            if min_frame is not None and min_frame > 0:
                print(f"[INFO] 先頭クリップ位置から推定: {min_frame}f")
                return min_frame
        except:
            pass
        return 0

# ==============================================================================
# 新フォルダ形式モード（simpleTalkGui.py 書き出しに対応：複数キャラ自動配置）
# ------------------------------------------------------------------------------
# 新形式クリップ名: キャラ名_ビデオトラック_オーディオトラック_状態_フレーム数_[開始-終了].png
#   状態: normal / blink / talk(10f) / talk_a / talk_b   ※blinkは10fのみ（新GUIは30f/60fを生成しない）
# ==============================================================================
# クリップ名自体に情報が含まれる場合（例: もち子_2_1_normal_[0000-0009].png）
# フレーム数は範囲 [開始-終了] から算出する（10f=[0000-0009], 30f=[0000-0029], 60f=[0000-0059]）。
NEW_CLIP_RE = re.compile(
    r'^(?P<id>.+?)_(?P<video>\d+)_(?P<audio>\d+)_'
    r'(?P<state>talk_a|talk_b|normal|blink|talk)_'
    r'\[(?P<fstart>\d+)-(?P<fend>\d+)\]\.png$',
    re.IGNORECASE,
)

# フォルダ名が情報を持つ場合（例: もち子_2_1_normal_10）
# Resolveにフォルダごとドロップするとクリップ名は「normal_[0000-0009].png」等に
# なりフォルダ名（キャラ名・トラック）が失われる。そこでソースファイルパスの
# 親フォルダ名を参照して情報を復元する。
NEW_FOLDER_RE = re.compile(
    r'^(?P<id>.+?)_(?P<video>\d+)_(?P<audio>\d+)_'
    r'(?P<state>talk_a|talk_b|normal|blink|talk)_(?P<frames>10|30|60)$',
    re.IGNORECASE,
)


def collect_all_clips(folder, clips=None):
    """メディアプール内の全クリップを再帰的に収集して返す"""
    if clips is None:
        clips = []
    try:
        clips.extend(folder.GetClipList() or [])
        for sub in folder.GetSubFolderList():
            collect_all_clips(sub, clips)
    except Exception:
        pass
    return clips


def parse_new_clip_name(clip_name):
    """新形式クリップ名を解析して辞書を返す（該当しなければ None）"""
    m = NEW_CLIP_RE.match(clip_name.strip())
    if not m:
        return None
    return {
        "id": m.group("id"),
        "video_track": int(m.group("video")),
        "audio_track": int(m.group("audio")),
        "state": m.group("state").lower(),
        "frames": int(m.group("fend")) - int(m.group("fstart")) + 1,
    }


def parse_new_folder_name(folder_name):
    """新形式フォルダ名を解析して辞書を返す（該当しなければ None）"""
    m = NEW_FOLDER_RE.match(folder_name.strip())
    if not m:
        return None
    return {
        "id": m.group("id"),
        "video_track": int(m.group("video")),
        "audio_track": int(m.group("audio")),
        "state": m.group("state").lower(),
        "frames": int(m.group("frames")),
    }


def get_clip_source_info(clip):
    """クリップから新形式情報を復元する。

    1) クリップ名自体に情報がある場合（ファイル名にキャラ名を入れた運用）
    2) それ以外はソースファイルパスの親フォルダ名から復元
       （フォルダごとドロップ時、クリップ名は「normal_[0000-0009].png」等に
        なるため、フォルダ名のキャラ名・トラック情報を使う）
    """
    try:
        info = parse_new_clip_name(clip.GetName())
        if info:
            return info
    except Exception:
        pass

    try:
        path = clip.GetClipProperty("File Path")
    except Exception:
        return None
    if not path:
        return None

    path = str(path).replace("\\", "/").strip("/")
    for seg in path.split("/"):
        info = parse_new_folder_name(seg)
        if info:
            return info
    return None


def auto_search_characters(root):
    """メディアプールから新形式クリップを検索し、キャラごとにまとめて返す"""
    chars = {}
    skipped_path = False
    for clip in collect_all_clips(root):
        info = get_clip_source_info(clip)
        if not info:
            skipped_path = True
            continue
        char = chars.setdefault(info["id"], {
            "id": info["id"],
            "video_track": info["video_track"],
            "audio_track": info["audio_track"],
            "clips": {},
        })
        char["clips"][f"{info['state']}_{info['frames']}"] = clip
    return chars, skipped_path


def _apply_transform(new_items, transform_props, mode, defaults):
    """配置後のクリップに変形プロパティを適用する（mode に従う）"""
    if mode == 0:
        return
    if mode == 2:
        return  # PRE_TRANSFORM（新モードでは事前変形前提のため何もしない）
    for nc in new_items:
        try:
            for pn, pv in transform_props.items():
                if pv == defaults.get(pn):
                    continue
                if pn in ("FlipX", "FlipY"):
                    pv = pv < 0
                nc.SetProperty(pn, pv)
        except Exception as e:
            print(f"[WARN] SetProperty失敗: {e}")


def place_character(pm, project, timeline, media_pool, char, fps, offset_frame, defaults, check_stop):
    """1キャラ分の自動配置を行う。配置成功ブロック数を返す。"""
    cid = char["id"]
    video_track = char["video_track"]
    audio_track = char["audio_track"]
    clips = char["clips"]

    normal10 = clips.get("normal_10")
    blink10 = clips.get("blink_10")
    talk10 = clips.get("talk_10")
    normal30 = clips.get("normal_30")
    talk_a30 = clips.get("talk_a_30")
    talk_b30 = clips.get("talk_b_30")
    normal60 = clips.get("normal_60")
    talk_a60 = clips.get("talk_a_60")
    talk_b60 = clips.get("talk_b_60")

    print("-" * 60)
    print(f"[新方式] キャラ: {cid} | video={video_track} audio={audio_track}")
    print(f"  素材: normal_10={'〇' if normal10 else '×'} blink_10={'〇' if blink10 else '×'} talk_10={'〇' if talk10 else '×'}")
    print(f"       normal_30={'〇' if normal30 else '×'} talk_a_30={'〇' if talk_a30 else '×'} talk_b_30={'〇' if talk_b30 else '×'}")
    print(f"       normal_60={'〇' if normal60 else '×'} talk_a_60={'〇' if talk_a60 else '×'} talk_b_60={'〇' if talk_b60 else '×'}")

    if not normal10:
        print(f"[WARN] '{cid}' に normal_10 がありません。スキップ。")
        return 0

    vb60 = all([normal60, talk_a60, talk_b60])
    vb30 = all([normal30, talk_a30, talk_b30])
    max_level = 6 if vb60 else (3 if vb30 else 1)

    # ---- 音声区間 ----
    audio_items = timeline.GetItemListInTrack("audio", audio_track)
    if not audio_items:
        print(f"[WARN] '{cid}' のオーディオトラック {audio_track} に音声がありません。スキップ。")
        return 0
    audio_items = sorted(audio_items, key=lambda it: it.GetStart())
    audio_ranges = [(it.GetStart(), it.GetEnd()) for it in audio_items]
    timeline_end = timeline.GetEndFrame()

    # ---- 基準変形（そのキャラのトラック先頭クリップから取得） ----
    transform_props = defaults.copy()
    video_items = timeline.GetItemListInTrack("video", video_track)
    if video_items:
        base_item = sorted(video_items, key=lambda x: x.GetStart())[0]
        try:
            def gp(item, key, default):
                v = item.GetProperty(key)
                return default if v is None else v
            rfx = gp(base_item, "FlipX", None)
            rfy = gp(base_item, "FlipY", None)
            for pn in ("Pan", "Tilt", "ZoomX", "ZoomY", "Rotation",
                       "CropLeft", "CropRight", "CropTop", "CropBottom", "Opacity", "CompositeMode"):
                transform_props[pn] = gp(base_item, pn, TRANSFORM_PARAMS[pn])
            transform_props["FlipX"] = -1.0 if rfx is True else (1.0 if rfx is False else TRANSFORM_PARAMS["FlipX"])
            transform_props["FlipY"] = -1.0 if rfy is True else (1.0 if rfy is False else TRANSFORM_PARAMS["FlipY"])
            print(f"[INFO] '{cid}' 基準変形をトラック{video_track}先頭クリップから取得: "
                  f"Pan={transform_props['Pan']} Tilt={transform_props['Tilt']} "
                  f"ZoomX={transform_props['ZoomX']} ZoomY={transform_props['ZoomY']} "
                  f"FlipX={transform_props['FlipX']} FlipY={transform_props['FlipY']}")
        except Exception as e:
            print(f"[WARN] '{cid}' 変形取得失敗。既定値を使用します: {e}")

    # ---- 既存占有範囲（プレースホルダー維持 or 前回分クリア） ----
    skip_ranges = []
    existing_n = len(video_items or [])
    if SKIP_OCCUPIED_RANGES:
        if existing_n and existing_n <= NEW_BATCH_SIZE + 5:
            for item in video_items:
                s, e = item.GetStart(), item.GetEnd()
                skip_ranges.append(((s // 10) * 10, ((e + 9) // 10) * 10))
            print(f"[INFO] '{cid}' トラック{video_track}に {existing_n} 個の占有区間（プレースホルダー）を維持・スキップします")
        elif existing_n:
            print(f"[INFO] '{cid}' トラック{video_track}の既存 {existing_n} クリップを前回実行と判断しクリアします")
            try:
                timeline.DeleteClips(video_items)
            except Exception as ex:
                print(f"[WARN] '{cid}' トラッククリア失敗: {ex}")
    else:
        if existing_n:
            try:
                timeline.DeleteClips(video_items)
            except Exception as ex:
                print(f"[WARN] '{cid}' トラッククリア失敗: {ex}")

    # ---- 10f境界に合わせた発話有効範囲 ----
    talk_valid_ranges = []
    for s, e in audio_ranges:
        s10 = ((s + 9) // 10) * 10
        e10 = (e // 10) * 10
        if s10 < e10:
            talk_valid_ranges.append((s10, e10))

    total_blocks = (timeline_end - offset_frame + 10 - 1) // 10
    if total_blocks <= 0:
        print(f"[WARN] '{cid}' 配置対象フレームがありません。")
        return 0

    # ---- Phase 1: ブロック状態決定（normal/talk 交互、blink は10fのみ） ----
    block_states = [None] * total_blocks
    is_last_talk = False
    next_blink = random.randint(5 * fps, 10 * fps)
    cur = offset_frame
    for bi in range(total_blocks):
        bs, be = cur, cur + 10
        has = any(s <= bs and be <= e for s, e in talk_valid_ranges)
        if has:
            block_states[bi] = "talk" if not is_last_talk else "normal"
            is_last_talk = not is_last_talk
        else:
            block_states[bi] = "normal"
            is_last_talk = False
        if cur >= next_blink and block_states[bi] == "normal":
            block_states[bi] = "blink"
            next_blink = cur + random.randint(5 * fps, 10 * fps)
        cur = be

    def in_talk(bi):
        bs = offset_frame + bi * 10
        return any(s <= bs and bs + 10 <= e for s, e in talk_valid_ranges)

    def in_skip(frame, dur):
        fe = frame + dur
        return any(not (e <= frame or s >= fe) for s, e in skip_ranges)

    # ---- Phase 2: 配置 ----
    buf = []
    success = 0

    def flush():
        nonlocal success, buf
        if not buf:
            return
        res = media_pool.AppendToTimeline(buf)
        if not res:
            print(f"[ERROR] '{cid}' バッチ配置失敗 (frame={buf[0]['recordFrame']})")
            buf = []
            return
        _apply_transform(res, transform_props, NEW_TRANSFORM_MODE, TRANSFORM_PARAMS)
        success += len(buf)
        buf = []

    def push(clip_obj, frame, dur):
        nonlocal buf
        buf.append({
            "mediaPoolItem": clip_obj,
            "startFrame": 0,
            "endFrame": dur,
            "recordFrame": frame,
            "trackIndex": video_track,
        })
        if len(buf) >= NEW_BATCH_SIZE:
            flush()

    def place(clip_obj, frame, dur):
        if SKIP_OCCUPIED_RANGES and in_skip(frame, dur):
            return
        push(clip_obj, frame, dur)

    get_talk_a = {6: talk_a60, 3: talk_a30, 1: talk10}
    get_talk_b = {6: talk_b60, 3: talk_b30, 1: talk10}
    get_normal = {6: normal60, 3: normal30, 1: normal10}

    bi = 0
    while bi < total_blocks:
        if check_stop():
            print(f"[STOP] '{cid}' 停止フラグ検出。中断します。")
            break
        bs = offset_frame + bi * 10
        state = block_states[bi]

        if SKIP_OCCUPIED_RANGES and in_skip(bs, 10):
            bi += 1
            continue

        # blink: 常に10f（素材がなければ normal で代替）
        if state == "blink":
            place(blink10 if blink10 else normal10, bs, 10)
            bi += 1
            continue

        # 音声区間（talk/normal 交互 → 30f/60f可変）
        seg_len = 0
        j = bi
        while j < total_blocks and in_talk(j):
            if block_states[j] == "blink":
                break
            if SKIP_OCCUPIED_RANGES and in_skip(offset_frame + j * 10, 10):
                break
            seg_len += 1
            j += 1

        if seg_len >= 1:
            if max_level >= 6:
                while seg_len >= 6:
                    p = [block_states[bi + i] for i in range(6)]
                    if p == ["talk", "normal", "talk", "normal", "talk", "normal"]:
                        place(get_talk_a[6], bs, 60); bi += 6; seg_len -= 6; bs += 60; continue
                    if p == ["normal", "talk", "normal", "talk", "normal", "talk"]:
                        place(get_talk_b[6], bs, 60); bi += 6; seg_len -= 6; bs += 60; continue
                    break
            if max_level >= 3:
                while seg_len >= 3:
                    p = [block_states[bi + i] for i in range(3)]
                    if "blink" in p:
                        break
                    if p == ["talk", "normal", "talk"]:
                        place(get_talk_a[3], bs, 30); bi += 3; seg_len -= 3; bs += 30; continue
                    if p == ["normal", "talk", "normal"]:
                        place(get_talk_b[3], bs, 30); bi += 3; seg_len -= 3; bs += 30; continue
                    break
            while seg_len >= 1:
                place(talk10 if block_states[bi] == "talk" else normal10, bs, 10)
                bi += 1; seg_len -= 1; bs += 10
            continue

        # 無音区間（normal）
        norm_len = 0
        j = bi
        while j < total_blocks and block_states[j] == "normal":
            if SKIP_OCCUPIED_RANGES and in_skip(offset_frame + j * 10, 10):
                break
            norm_len += 1
            j += 1

        if norm_len >= 1:
            if max_level >= 6:
                while norm_len >= 6:
                    place(get_normal[6], bs, 60); bi += 6; norm_len -= 6; bs += 60
            if max_level >= 3:
                while norm_len >= 3:
                    place(get_normal[3], bs, 30); bi += 3; norm_len -= 3; bs += 30
            while norm_len >= 1:
                place(normal10, bs, 10); bi += 1; norm_len -= 1; bs += 10
            continue

        bi += 1

    flush()
    print(f"[INFO] '{cid}' 配置完了: {success} ブロック")
    return success


def main_new_format():
    print("=" * 60)
    print(" キャラ自動口パク配置（新フォルダ形式・複数キャラ対応）")
    print("=" * 60)

    # 停止フラグ監視パス（ローカル初期化）
    stop_paths = set()
    stop_paths.add(os.getcwd())
    try:
        sp = os.path.dirname(os.path.abspath(sys.argv[0]))
        if os.path.isdir(sp):
            stop_paths.add(sp)
    except Exception:
        pass
    stop_paths = [os.path.normpath(p) for p in sorted(stop_paths)]

    def check_stop():
        for base in stop_paths:
            for suffix in ("", ".txt"):
                fp = os.path.join(base, STOP_FLAG_FILE + suffix)
                if os.path.exists(fp):
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
                    print(f"[STOP] 停止フラグを検出: {fp}")
                    return fp
        return None

    # Resolve 初期化
    try:
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject()
        if not project:
            print("[ERROR] 現在開いているプロジェクトが見つかりません。")
            return
        timeline = project.GetCurrentTimeline()
        if not timeline:
            print("[ERROR] アクティブなタイムラインが見つかりません。")
            return
        media_pool = project.GetMediaPool()
        root = media_pool.GetRootFolder()
    except NameError:
        print("[ERROR] 'resolve' オブジェクトが見つかりません。")
        print("        DaVinci Resolve内部のコンソールまたは外部APIから実行してください。")
        return
    except Exception as e:
        print(f"[ERROR] 初期化エラー: {e}")
        return

    # フレームレート
    FPS = 60
    try:
        fps_raw = project.GetSetting("timelineFrameRate")
        m = re.search(r"([\d.]+)", str(fps_raw))
        FPS = round(float(m.group(1))) if m else 60
        print(f"[INFO] フレームレート: {FPS}fps")
    except Exception:
        pass

    OFFSET_FRAME = detect_start_offset(timeline, project, FPS)

    # 自動検索
    chars, skipped_path = auto_search_characters(root)
    if not chars:
        print("[ERROR] メディアプールに新形式の連番PNGクリップが見つかりません。")
        print("        検出方法: クリップ名 または ソースフォルダ名")
        print("        形式: キャラ名_ビデオトラック_オーディオトラック_状態_フレーム数")
        print("        例  : もち子_2_1_normal_10  (フォルダごとドロップでOK)")
        return
    if skipped_path:
        print("[WARN] 情報を復元できないクリップが存在しました（新形式対象外とみなし無視）。")
    print(f"[INFO] 検出したキャラクター: {', '.join(chars.keys())}")

    defaults = TRANSFORM_PARAMS.copy()
    start_time = time.time()
    total_placed = 0
    for cid in chars:
        if check_stop():
            print(f"[STOP] 全キャラ処理を中断します。")
            break
        try:
            total_placed += place_character(pm, project, timeline, media_pool,
                                            chars[cid], FPS, OFFSET_FRAME, defaults, check_stop)
        except Exception as e:
            print(f"[ERROR] キャラ '{cid}' の配置に失敗しました: {e}")

    print("=" * 60)
    print(f"[DONE] 全キャラの処理が完了しました。")
    print(f"       配置合計ブロック数: {total_placed} (処理時間 {time.time() - start_time:.1f}秒)")
    print("=" * 60)


# ==============================================================================
# メイン処理
# ==============================================================================
def main():
    if USE_NEW_FOLDER_FORMAT:
        main_new_format()
        return
    print("=" * 60)
    print(" キャラクター自動口パク・まばたき配置システム (v2.0 可変ブロック対応)")
    print("=" * 60)

    # 1. 停止フラグの検索パスを初期化
    global STOP_CHECK_PATHS
    check_paths = set()
    check_paths.add(os.getcwd())
    # sys.argv[0] がスクリプトパスの場合
    try:
        sp = os.path.dirname(os.path.abspath(sys.argv[0]))
        if os.path.isdir(sp):
            check_paths.add(sp)
    except:
        pass
    # デスクトップとTEMPも対象に（ユーザーが書き込み可能な場所）
    for env_key in ['USERPROFILE', 'HOME']:
        val = os.environ.get(env_key)
        if val:
            dp = os.path.join(val, 'Desktop')
            if os.path.isdir(dp):
                check_paths.add(dp)
    tmp = os.environ.get('TEMP')
    if tmp and os.path.isdir(tmp):
        check_paths.add(tmp)
    STOP_CHECK_PATHS = [os.path.normpath(p) for p in sorted(check_paths)]
    print("[INFO] 停止フラグ監視パス:")
    for p in STOP_CHECK_PATHS:
        print(f"       {os.path.join(p, STOP_FLAG_FILE)}")
    print(f"       上記いずれかに stop_flag.txt を作成すると安全停止します")

    # 2. Resolve APIの初期化チェック
    try:
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject()
        if not project:
            raise ValueError("現在開いているプロジェクトが見つかりません。")
        
        timeline = project.GetCurrentTimeline()
        if not timeline:
            raise ValueError("アクティブなタイムラインが見つかりません。編集用のタイムラインを開いてください。")
        
        media_pool = project.GetMediaPool()
        root = media_pool.GetRootFolder()
    except NameError:
        print("[ERROR] 'resolve' オブジェクトが見つかりません。")
        print("        このスクリプトはDaVinci Resolve内部のコンソール、または外部API連携から実行してください。")
        return
    except Exception as e:
        print(f"[ERROR] 初期化エラー: {e}")
        return

    # フレームレート自動検出
    try:
        fps_raw = project.GetSetting("timelineFrameRate")
        match = re.search(r"([\d.]+)", str(fps_raw))
        FPS = float(match.group(1)) if match else 60.0
        FPS = round(FPS)
        print(f"[INFO] フレームレート: {FPS}fps (raw='{fps_raw}')")
    except Exception as e:
        print(f"[WARN] FPS取得失敗: {e}")
        FPS = 60

    # 開始タイムコードから配置オフセット検出
    OFFSET_FRAME = detect_start_offset(timeline, project, FPS)

    # 2. メディアプールからの素材取得
    normal_clip = find_clip(root, NORMAL_CLIP_NAME)
    talk_clip = find_clip(root, TALK_CLIP_NAME)
    blink_clip = find_clip(root, BLINK_CLIP_NAME)

    if not all([normal_clip, talk_clip, blink_clip]):
        print("[ERROR] メディアプールに必要な連番PNG素材が見つかりません。名称を確認してください。")
        print(f"        通常(Normal): {'〇' if normal_clip else '×'} ({NORMAL_CLIP_NAME})")
        print(f"        口開(Talk)  : {'〇' if talk_clip else '×'} ({TALK_CLIP_NAME})")
        print(f"        目閉(Blink) : {'〇' if blink_clip else '×'} ({BLINK_CLIP_NAME})")
        return
    print("[INFO] 10fブロック素材を検出しました。")

    # 30f/60f素材の検出（可変ブロックモード）
    vb_60f = False
    vb_30f = False
    normal_30f = talk_30f_a = talk_30f_b = blink_30f = None
    normal_60f = talk_60f_a = talk_60f_b = blink_60f = None

    if USE_VARIABLE_BLOCK:
        normal_60f = find_clip(root, NORMAL_60F_CLIP_NAME)
        talk_60f_a = find_clip(root, TALK_60F_A_CLIP_NAME)
        talk_60f_b = find_clip(root, TALK_60F_B_CLIP_NAME)
        blink_60f  = find_clip(root, BLINK_60F_CLIP_NAME)
        vb_60f = all([normal_60f, talk_60f_a, talk_60f_b, blink_60f])

        normal_30f = find_clip(root, NORMAL_30F_CLIP_NAME)
        talk_30f_a = find_clip(root, TALK_30F_A_CLIP_NAME)
        talk_30f_b = find_clip(root, TALK_30F_B_CLIP_NAME)
        blink_30f  = find_clip(root, BLINK_30F_CLIP_NAME)
        vb_30f = all([normal_30f, talk_30f_a, talk_30f_b, blink_30f])

        if vb_60f:
            print("[INFO] 60f/30f/10f全ブロック素材を検出。可変ブロックモード（60f優先）で動作します。")
        elif vb_30f:
            print("[INFO] 30f/10fブロック素材を検出。可変ブロックモード（30fまで）で動作します。")
        else:
            print("[WARN] 30f/60fブロック素材が見つかりません。10f固定モードにフォールバックします。")
            print(f"        30f: normal={'〇' if normal_30f else '×'} talk_a={'〇' if talk_30f_a else '×'} talk_b={'〇' if talk_30f_b else '×'} blink={'〇' if blink_30f else '×'}")
            print(f"        60f: normal={'〇' if normal_60f else '×'} talk_a={'〇' if talk_60f_a else '×'} talk_b={'〇' if talk_60f_b else '×'} blink={'〇' if blink_60f else '×'}")
    else:
        vb_30f = vb_60f = False

# PRE_TRANSFORM モード用の変形済みクリップ取得
    normal_clip_trans = talk_clip_trans = blink_clip_trans = None
    normal_30f_trans = talk_30f_a_trans = talk_30f_b_trans = blink_30f_trans = None
    normal_60f_trans = talk_60f_a_trans = talk_60f_b_trans = blink_60f_trans = None

    def find_trans_clip(root, base_name):
        """変形済みクリップを検索（_trans_ で始まる名前を探す）"""
        for clip in root.GetClipList():
            if clip.GetName().startswith(base_name + "_trans_"):
                return clip
        return None

    if TRANSFORM_MODE == 2:
        print(f"[DEBUG] TRANSFORM_MODE=2: 変形済みクリップ検索開始")
        normal_clip_trans = find_trans_clip(root, NORMAL_CLIP_NAME)
        talk_clip_trans = find_trans_clip(root, TALK_CLIP_NAME)
        blink_clip_trans = find_trans_clip(root, BLINK_CLIP_NAME)
        normal_30f_trans = find_trans_clip(root, NORMAL_30F_CLIP_NAME)
        talk_30f_a_trans = find_trans_clip(root, TALK_30F_A_CLIP_NAME)
        talk_30f_b_trans = find_trans_clip(root, TALK_30F_B_CLIP_NAME)
        blink_30f_trans = find_trans_clip(root, BLINK_30F_CLIP_NAME)
        normal_60f_trans = find_trans_clip(root, NORMAL_60F_CLIP_NAME)
        talk_60f_a_trans = find_trans_clip(root, TALK_60F_A_CLIP_NAME)
        talk_60f_b_trans = find_trans_clip(root, TALK_60F_B_CLIP_NAME)
        blink_60f_trans = find_trans_clip(root, BLINK_60F_CLIP_NAME)
        print(f"[DEBUG] 変形済みクリップ検索完了: normal={'〇' if normal_clip_trans else '×'} talk={'〇' if talk_clip_trans else '×'} blink={'〇' if blink_clip_trans else '×'}")
        print(f"[DEBUG] PRE_TRANSFORM 生成フェーズ開始")

    # 3. 既存のキャラクター用トラックから位置情報の取得
    video_items = timeline.GetItemListInTrack("video", VIDEO_TRACK)
    
    # デフォルトの変形パラメータ (TRANSFORM_PARAMS からコピー)
    transform_props = TRANSFORM_PARAMS.copy()
    
    if video_items:
        # トラック2に既に存在する「最初のクリップ」を基準として座標・ズーム・反転・回転を読み取る
        base_item = sorted(video_items, key=lambda x: x.GetStart())[0]
        try:
            def get_prop(item, key, default):
                val = item.GetProperty(key)
                if val is None:
                    return default
                return val
            
            # 既存クリップから取得（Resolve APIは FlipX/FlipY を bool で返す）
            raw_flip_x = get_prop(base_item, "FlipX", None)
            raw_flip_y = get_prop(base_item, "FlipY", None)
            
            transform_props["Pan"]      = get_prop(base_item, "Pan", TRANSFORM_PARAMS["Pan"])
            transform_props["Tilt"]     = get_prop(base_item, "Tilt", TRANSFORM_PARAMS["Tilt"])
            transform_props["ZoomX"]    = get_prop(base_item, "ZoomX", TRANSFORM_PARAMS["ZoomX"])
            transform_props["ZoomY"]    = get_prop(base_item, "ZoomY", TRANSFORM_PARAMS["ZoomY"])
            # FlipX/FlipY: bool -> float (1.0 / -1.0) 変換
            transform_props["FlipX"]    = -1.0 if raw_flip_x is True else (1.0 if raw_flip_x is False else TRANSFORM_PARAMS["FlipX"])
            transform_props["FlipY"]    = -1.0 if raw_flip_y is True else (1.0 if raw_flip_y is False else TRANSFORM_PARAMS["FlipY"])
            transform_props["Rotation"] = get_prop(base_item, "Rotation", TRANSFORM_PARAMS["Rotation"])
            
            # 追加プロパティ取得
            transform_props["CropLeft"]   = get_prop(base_item, "CropLeft", 0.0)
            transform_props["CropRight"]  = get_prop(base_item, "CropRight", 0.0)
            transform_props["CropTop"]    = get_prop(base_item, "CropTop", 0.0)
            transform_props["CropBottom"] = get_prop(base_item, "CropBottom", 0.0)
            transform_props["Opacity"]    = get_prop(base_item, "Opacity", 1.0)
            transform_props["CompositeMode"] = get_prop(base_item, "CompositeMode", 0)
            
            print("[INFO] 既存クリップから位置情報を取得しました:")
            print(f"       位置(X, Y): ({transform_props['Pan']}, {transform_props['Tilt']})")
            print(f"       ズーム(X, Y): ({transform_props['ZoomX']}, {transform_props['ZoomY']})")
            print(f"       反転(X, Y): ({transform_props['FlipX']}, {transform_props['FlipY']})")
            print(f"       回転: {transform_props['Rotation']}度")
            print(f"       クロップ(L,R,T,B): ({transform_props['CropLeft']}, {transform_props['CropRight']}, {transform_props['CropTop']}, {transform_props['CropBottom']})")
            print(f"       不透明度: {transform_props['Opacity']}, 合成モード: {transform_props['CompositeMode']}")
        except Exception as e:
            print(f"[WARNING] 位置情報の取得に失敗しました(デフォルト値を使用します): {e}")
    else:
        print("[WARNING] ビデオトラックに基準となるクリップがありません。デフォルト位置(中央・等倍)で配置します。")

    # 4. オーディオトラックの解析
    audio_items = timeline.GetItemListInTrack("audio", AUDIO_TRACK)
    if not audio_items:
        print(f"[ERROR] オーディオトラック {AUDIO_TRACK} に音声クリップが配置されていません。")
        return
    
    audio_items = sorted(audio_items, key=lambda item: item.GetStart())
    audio_ranges = [(item.GetStart(), item.GetEnd()) for item in audio_items]
    timeline_end = timeline.GetEndFrame()
    
    # 5. 既存クリップの占有範囲を記録（配置スキップ用）
    skip_ranges = []      # (expanded_s, expanded_e) 配置スキップ用
    skip_raw_ranges = []  # (raw_s, raw_e) 隙間埋め用（実位置）
    if SKIP_OCCUPIED_RANGES:
        existing = timeline.GetItemListInTrack("video", VIDEO_TRACK)
        if existing and len(existing) <= 50:  # 50以下＝手動プレースホルダー → トラックを残す
            for item in existing:
                s_raw, e_raw = item.GetStart(), item.GetEnd()
                clip_name = getattr(item, "GetName", lambda: "unknown")()
                # 10fブロック境界に拡張（端数ギャップ防止）
                s = (s_raw // 10) * 10
                e = ((e_raw + 9) // 10) * 10
                skip_ranges.append((s, e))
                skip_raw_ranges.append((s_raw, e_raw))
                def fc(f):
                    m = f // (60*FPS)
                    s = (f % (60*FPS)) // FPS
                    fr = f % FPS
                    return f"{m:02d}:{s:02d}:{fr:02d}"
                print(f"[DEBUG] 既存クリップ検出: '{clip_name}' raw={s_raw}-{e_raw} ({fc(s_raw)}-{fc(e_raw)}) -> expanded={s}-{e} ({fc(s)}-{fc(e)})")
            print(f"[INFO] トラック{VIDEO_TRACK}に {len(skip_ranges)} 個の占有区間を検出しました（プレースホルダー維持・該当区間をスキップします）")
        elif existing:
            print(f"[INFO] トラック{VIDEO_TRACK}に {len(existing)} 個のクリップがあります（スクリプト前回実行と判断、クリアして再配置します）")
            clear_track_clips(timeline, "video", VIDEO_TRACK)
        else:
            pass  # トラック空 → 通常通り配置
    else:
        # SKIP_OCCUPIED_RANGES=False → 従来通りクリア
        clear_track_clips(timeline, "video", VIDEO_TRACK)

    # ===== PRE_TRANSFORM モード: Fusionで事前変形クリップ生成 =====
    transformed_clips = {}  # (clip_name, mode) -> transformed_clip
    
    def generate_transformed_clip(project, media_pool, source_clip_name, transform_props):
        """Fusionで変形済みクリップを生成し、メディアプールに登録して返す"""
        import tempfile
        import shutil
        if not source_clip_name:
            return None
        
        # 変形済みクリップ名
        safe_name = source_clip_name.replace("[", "_").replace("]", "_").replace(".", "_")
        trans_name = f"{safe_name}_trans_P{transform_props['Pan']:.1f}_T{transform_props['Tilt']:.1f}_ZX{transform_props['ZoomX']:.2f}_ZY{transform_props['ZoomY']:.2f}_FX{transform_props['FlipX']:.1f}_FY{transform_props['FlipY']:.1f}_R{transform_props['Rotation']:.1f}"
        
        # 既に生成済みなら再利用
        if trans_name in transformed_clips:
            return transformed_clips[trans_name]
        
        try:
            # Fusionで変形処理
            print(f"[DEBUG] Fusion取得開始: {source_clip_name}")
            fusion = resolve.Fusion()
            if not fusion:
                print(f"[WARNING] Fusion利用不可: {source_clip_name}")
                return None
            print(f"[DEBUG] Fusion取得完了")
            
            # 一時コンポジション作成
            print(f"[DEBUG] コンポジション作成開始")
            comp = fusion.NewComp()
            if not comp:
                print(f"[WARNING] コンポジション作成失敗: {source_clip_name}")
                return None
            print(f"[DEBUG] コンポジション作成完了")
            
            # ソースクリップ検索
            print(f"[DEBUG] ソースクリップ検索開始: {source_clip_name}")
            source_clip = None
            root_folder = media_pool.GetRootFolder()
            for clip in root_folder.GetClipList():
                if clip.GetName() == source_clip_name:
                    source_clip = clip
                    break
            
            if not source_clip:
                print(f"[WARNING] ソースクリップ未発見: {source_clip_name}")
                return None
            print(f"[DEBUG] ソースクリップ発見: {source_clip_name}")
            
            # ソースクリップのファイルパスを取得
            print(f"[DEBUG] ソースクリップのファイルパス取得開始")
            clip_path = None
            try:
                # メディアプールクリップからファイルパス取得を試行
                clip_path = source_clip.GetClipProperty("File Path")
                if clip_path and clip_path != "":
                    clip_path = clip_path
                else:
                    # パスが取れない場合はクリップ名から推測（連番PNGの場合）
                    clip_path = source_clip_name
            except Exception as e:
                print(f"[WARNING] ファイルパス取得失敗、クリップ名を使用: {e}")
                clip_path = source_clip_name
            
            # 日本語パスなどFusion Loaderが扱えないパスの場合は一時ディレクトリにコピー
            if clip_path and any(ord(c) > 127 for c in clip_path):
                print(f"[DEBUG] 日本語パス検出、一時ディレクトリにコピーします: {clip_path}")
                temp_dir = tempfile.mkdtemp(prefix="lipsync_src_")
                # フォルダ名のみ抽出して一時フォルダにコピー
                base_name = os.path.basename(clip_path)
                # 連番PNGパターン normal_[0000-0009].png -> normal_0000.png など
                pattern_match = re.match(r'^(.+)\[(\d+)-(\d+)\]\.(\w+)$', base_name)
                if pattern_match:
                    base, start_f, end_f, ext = pattern_match.groups()
                    start_i = int(start_f)
                    end_i = int(end_f)
                    # 全フレームをコピー
                    for fi in range(start_i, end_i + 1):
                        src_file = os.path.join(clip_path.replace(f'[{start_f}-{end_f}]', f'{fi:04d}'))
                        if os.path.exists(src_file):
                            dst_file = os.path.join(temp_dir, f"{base}_{fi:04d}.{ext}")
                            shutil.copy2(src_file, dst_file)
                    clip_path = temp_dir
                else:
                    # パターンと合わない場合は全体をコピー先に
                    shutil.copytree(clip_path, temp_dir, dirs_exist_ok=True)
                    clip_path = temp_dir
                print(f"[DEBUG] 一時パスに変更: {clip_path}")
            else:
                print(f"[DEBUG] ASCIIパスそのまま使用: {clip_path}")
            
            # Loader作成（ファイルパス指定）
            print(f"[DEBUG] Loader作成開始")
            loader = comp.AddTool("Loader")
            loader.Clip = clip_path  # ファイルパス文字列を指定
            # フレーム範囲を設定（Loaderは初期値で-2147483648になることがあるため）
            try:
                loader.StartFrame = 0
                loader.EndFrame = 59
                print(f"[DEBUG] Loaderフレーム範囲設定: 0-59")
            except Exception as e:
                print(f"[DEBUG] Loaderフレーム範囲設定スキップ: {e}")
            print(f"[DEBUG] Loader作成・Clip設定完了: {clip_path}")
            
            # Transformツール追加
            print(f"[DEBUG] Transformツール作成開始")
            transform = comp.AddTool("Transform")
            print(f"[DEBUG] Transformツール作成完了")
            transform.Input = loader.Output
            print(f"[DEBUG] Transform接続完了")
            
            # パラメータ適用
            print(f"[DEBUG] Transformパラメータ適用開始")
            transform.Center = {1: transform_props["Pan"], 2: transform_props["Tilt"]}
            transform.Size = {1: transform_props["ZoomX"], 2: transform_props["ZoomY"]}
            transform.FlipX = (transform_props["FlipX"] < 0)
            transform.FlipY = (transform_props["FlipY"] < 0)
            if transform_props["Rotation"] != 0:
                transform.Angle = transform_props["Rotation"]
            # Cropは Transform ツールでは直接サポートされていないためスキップ
            # Opacity は Transform ではなく合成時に調整
            print(f"[DEBUG] Transformパラメータ適用完了")
            
            # Saverで出力（連番PNGとして一時フォルダへ）
            print(f"[DEBUG] Saver/TempDir準備開始")
            import tempfile
            import os
            import glob
            temp_dir = tempfile.mkdtemp(prefix="lipsync_trans_")
            output_pattern = os.path.join(temp_dir, f"{trans_name}_%04d.png")
            
            print(f"[DEBUG] 生成開始: {trans_name} -> {temp_dir}")
            
            saver = comp.AddTool("Saver")
            saver.Input = transform.Output
            saver.Clip = output_pattern
            saver.Format = "PNG"
            # Saver設定を明示的に設定（ダイアログ抑制）
            saver["Clip"] = output_pattern
            saver["Format"] = "PNG"
            print(f"[DEBUG] Saver設定完了")
            
            # レンダリング実行（非対話的・ダイアログ抑制）
            print(f"[DEBUG] レンダリング開始: {trans_name}")
            try:
                # comp.Render() を使用（標準的な Fusion API）
                comp.Render({
                    "Start": 0,
                    "End": 59,  # 最大60フレーム（60f対応）
                    "Tool": saver,
                    "Wait": True
                })
                print(f"[DEBUG] レンダリング完了: {trans_name}")
            except Exception as render_e:
                print(f"[WARNING] レンダリング失敗: {render_e}")
                # 代替手段: saver.Render() を試す
                try:
                    print(f"[DEBUG] 代替レンダリング試行: saver.Render()")
                    saver.Render({"Wait": True})
                    print(f"[DEBUG] 代替レンダリング完了: {trans_name}")
                except Exception as render_e2:
                    print(f"[ERROR] レンダリング完全失敗: {render_e2}")
                    raise
            
            print(f"[DEBUG] レンダリング完了: {trans_name}")
            
            # 生成されたファイルを取得してインポート
            generated_files = sorted(glob.glob(os.path.join(temp_dir, f"{trans_name}_*.png")))
            print(f"[DEBUG] 生成ファイル数: {len(generated_files)}")
            if not generated_files:
                print(f"[WARNING] ファイル生成されず: {trans_name}")
                return None
            
            print(f"[DEBUG] インポート開始: {len(generated_files)}ファイル")
            new_clips = media_pool.ImportMedia(generated_files)
            if new_clips and len(new_clips) > 0:
                trans_clip = new_clips[0]
                transformed_clips[trans_name] = trans_clip
                print(f"[INFO] 変形済みクリップ生成: {trans_name}")
                return trans_clip
            else:
                print(f"[WARNING] 変形クリップインポート失敗: {trans_name}")
                return None
                
        except Exception as e:
            print(f"[WARNING] 変形生成失敗 ({source_clip_name}): {e}")
            return None

    # PRE_TRANSFORM モードの場合、全クリップを事前生成
    if TRANSFORM_MODE == 2:
        print("[INFO] PRE_TRANSFORM モード: 変形済みクリップを生成中...")
        clip_names = [
            NORMAL_CLIP_NAME, TALK_CLIP_NAME, BLINK_CLIP_NAME,
            NORMAL_30F_CLIP_NAME, TALK_30F_A_CLIP_NAME, TALK_30F_B_CLIP_NAME, BLINK_30F_CLIP_NAME,
            NORMAL_60F_CLIP_NAME, TALK_60F_A_CLIP_NAME, TALK_60F_B_CLIP_NAME, BLINK_60F_CLIP_NAME
        ]
        for cn in clip_names:
            generate_transformed_clip(project, media_pool, cn, transform_props)
        print(f"[INFO] 変形済みクリップ生成完了: {len(transformed_clips)}個")

    def in_skip_zone(frame, duration):
        fe = frame + duration
        for s, e in skip_ranges:
            if not (e <= frame or s >= fe):
                return True
        return False

    # クリップ選択ヘルパー（TRANSFORM_MODE に応じて元/変形済みを返す）
    def get_clip(base_clip, trans_clip=None):
        if TRANSFORM_MODE == 2 and trans_clip:
            return trans_clip
        return base_clip

    # 6. ヘルパー関数: バッファ追加と一括配置
    def flush_buffer(items_buf):
        if not items_buf:
            return 0
        new_items = media_pool.AppendToTimeline(items_buf)
        if not new_items:
            print(f"[ERROR] バッチ配置失敗 (frame {items_buf[0]['recordFrame']})")
            return -1
        
        # TRANSFORM_MODE による変形適用
        if TRANSFORM_MODE == 1:  # APPLY_AFTER: 配置後にSetProperty
            # デフォルト値と異なるプロパティのみ適用（高速化）
            defaults = TRANSFORM_PARAMS
            for new_clip in new_items:
                try:
                    for prop_name, prop_value in transform_props.items():
                        if prop_value == defaults.get(prop_name):
                            continue  # デフォルト値ならスキップ
                        # FlipX/FlipY: float (1.0/-1.0) -> bool (True/False) 変換
                        if prop_name in ("FlipX", "FlipY"):
                            prop_value = (prop_value < 0)
                        new_clip.SetProperty(prop_name, prop_value)
                except Exception as e:
                    print(f"[WARNING] SetProperty失敗: {e}")
        elif TRANSFORM_MODE == 0:  # SKIP: SetPropertyしない
            pass
        # TRANSFORM_MODE == 2 (PRE_TRANSFORM) は事前変形済みのため何もしない
        
        return len(items_buf)

    def push_item(buf, clip, frame, duration):
        buf.append({
            "mediaPoolItem": clip,
            "startFrame": 0,
            "endFrame": duration,
            "recordFrame": frame,
            "trackIndex": VIDEO_TRACK
        })
        if len(buf) >= 50:
            return True
        return False

    def check_stop_flag():
        for base in STOP_CHECK_PATHS:
            for suffix in ["", ".txt"]:
                fp = os.path.join(base, STOP_FLAG_FILE + suffix)
                if os.path.exists(fp):
                    try:
                        os.remove(fp)
                    except:
                        pass
                    return fp
        return None

    # ==========================================================================
    # 6. タイムライン生成
    # ==========================================================================
    print("[INFO] タイムラインの構築を開始します...")
    total_blocks = (timeline_end - OFFSET_FRAME + BLOCK_FRAMES - 1) // BLOCK_FRAMES
    print(f"[INFO] 総フレーム数: {timeline_end - OFFSET_FRAME} / ブロック数: {total_blocks}")
    start_time = time.time()
    buffer_items = []
    success_count = 0
    stopped = False

    # -------------------------------------------------------------------------
    # 6-a. 従来方式（10f固定）
    # -------------------------------------------------------------------------
    if not (vb_30f or vb_60f):
        print("[INFO] 10f固定モードで配置します...")
        current_frame = OFFSET_FRAME
        next_blink_frame = random.randint(5 * FPS, 10 * FPS)
        is_last_talk = False
        progress_last = -1

        while current_frame < timeline_end:
            block_start = current_frame
            block_end = current_frame + BLOCK_FRAMES

            # 停止フラグ
            flag = check_stop_flag()
            if flag:
                print(f"[STOP] 停止フラグを検出: {flag}")
                stopped = True
                break

            # 進捗
            total_range = timeline_end - OFFSET_FRAME
            done = current_frame - OFFSET_FRAME
            progress = 100 * done // total_range if total_range else 0
            if progress > progress_last:
                progress_last = progress
                print(f"[PROGRESS] {progress}% ({done}/{total_range}) 経過:{time.time()-start_time:.1f}秒")

            # 音声判定
            has_audio = False
            for s, e in audio_ranges:
                if not (e <= block_start or s >= block_end):
                    has_audio = True
                    break

            # 状態決定
            clip = normal_clip
            if has_audio:
                if is_last_talk:
                    clip = normal_clip
                    is_last_talk = False
                else:
                    clip = talk_clip
                    is_last_talk = True
            else:
                is_last_talk = False

            # まばたき
            if current_frame >= next_blink_frame and clip == normal_clip:
                clip = get_clip(blink_clip, blink_clip_trans)
                next_blink_frame = current_frame + random.randint(5 * FPS, 10 * FPS)

            if SKIP_OCCUPIED_RANGES and in_skip_zone(block_start, BLOCK_FRAMES):
                pass
            elif push_item(buffer_items, get_clip(clip), block_start, BLOCK_FRAMES):
                cnt = flush_buffer(buffer_items)
                if cnt >= 0: success_count += cnt
                buffer_items = []

            current_frame = block_end

        # 最終バッファフラッシュ
        if buffer_items:
            cnt = flush_buffer(buffer_items)
            if cnt >= 0: success_count += cnt
            buffer_items = []

    # -------------------------------------------------------------------------
    # 6-b. 可変ブロック方式（10f/30f/60f）
    # -------------------------------------------------------------------------
    else:
        max_block_level = 6 if vb_60f else (3 if vb_30f else 1)
        size_parts = [p for p in ["30f","60f"] if (p=="30f" and vb_30f) or (p=="60f" and vb_60f)]
        print(f"[INFO] 可変ブロック方式（10f{'/' + '/'.join(size_parts) if size_parts else ''}）で配置します...")

        # 発話区間を10f境界にトリミングして事前計算
        #  audio [s, e) → talk有効範囲 [ceil(s/10)*10, floor(e/10)*10)
        def frame_to_tc(f, fps=FPS):
            h = f // (3600 * fps)
            m = (f % (3600 * fps)) // (60 * fps)
            s = (f % (60 * fps)) // fps
            fr = f % fps
            return f"{h:02d}:{m:02d}:{s:02d}:{fr:02d}"

        talk_valid_ranges = []
        for s, e in audio_ranges:
            s10 = ((s + 9) // 10) * 10
            e10 = (e // 10) * 10
            if s10 < e10:
                talk_valid_ranges.append((s10, e10))
            else:
                print(f"[DEBUG] 音声 {s}-{e} ({frame_to_tc(s)}-{frame_to_tc(e)}) は10f未満のため talk から除外")

        print(f"[DEBUG] 音声区間: {[(s, e, frame_to_tc(s), frame_to_tc(e)) for s, e in audio_ranges]}")
        print(f"[DEBUG] talk有効範囲(10f境界): {[(s, e, frame_to_tc(s), frame_to_tc(e)) for s, e in talk_valid_ranges]}")

        # Phase 1: 10fブロック単位で全フレームの状態を事前決定
        block_states = [None] * total_blocks
        is_last_talk = False
        next_blink_frame = random.randint(5 * FPS, 10 * FPS)
        cur = OFFSET_FRAME

        for bi in range(total_blocks):
            bs = cur
            be = cur + BLOCK_FRAMES

# 発話判定：ブロックがトリミング済み発話範囲に完全内包されているか
            has_audio = False
            for s, e in talk_valid_ranges:
                if s <= bs and be <= e:
                    has_audio = True
                    break

            if has_audio:
                if is_last_talk:
                    block_states[bi] = "normal"
                    is_last_talk = False
                else:
                    block_states[bi] = "talk"
                    is_last_talk = True
            else:
                block_states[bi] = "normal"
                is_last_talk = False

            # まばたき
            if cur >= next_blink_frame and block_states[bi] == "normal":
                block_states[bi] = "blink"
                next_blink_frame = cur + random.randint(5 * FPS, 10 * FPS)

            cur = be

        # block_states サマリ（talk/normal/blink の切り替わり位置）
        prev_state = None
        talk_segments = []
        seg_start = None
        for bi, st in enumerate(block_states):
            if st != prev_state:
                if prev_state == "talk" and seg_start is not None:
                    talk_segments.append((seg_start, bi))
                if st == "talk":
                    seg_start = bi
                prev_state = st
        if prev_state == "talk" and seg_start is not None:
            talk_segments.append((seg_start, len(block_states)))
        
        print(f"[DEBUG] talkブロック区間: {[(s, e, s*10+OFFSET_FRAME, e*10+OFFSET_FRAME) for s, e in talk_segments]}")

        # Phase 2: 音声区間ベースでブロックをグループ化し最適サイズで配置
        skip_blocks = [in_skip_zone(OFFSET_FRAME + bi * BLOCK_FRAMES, BLOCK_FRAMES) for bi in range(total_blocks)]
        bi = 0
        total_placed_frames = 0
        progress_last = -1
        buf_items = []
        last_placed_end = OFFSET_FRAME  # 直前に配置したクリップの終端フレーム

        def fill_gap_if_needed(target_frame):
            """target_frame と last_placed_end の間に 1-9f の隙間があれば normal で埋める"""
            nonlocal last_placed_end, success_count, buf_items
            if target_frame <= last_placed_end:
                return
            gap = target_frame - last_placed_end
            if 0 < gap < BLOCK_FRAMES:
                print(f"[DEBUG] 隙間埋め: {last_placed_end}-{target_frame} ({frame_to_tc(last_placed_end)}-{frame_to_tc(target_frame)}) gap={gap}f")
                place_short_normal(last_placed_end, gap)

        def place_short_normal(frame, duration):
            """normalクリップの先頭 duration フレームだけで短く配置"""
            nonlocal success_count, buf_items, last_placed_end
            # normal_clip は 10f の連番。startFrame=0, endFrame=duration で先頭 duration フレームのみ使用
            if push_item(buf_items, get_clip(normal_clip, normal_clip_trans), frame, duration):
                cnt = flush_buffer(buf_items)
                if cnt >= 0:
                    success_count += cnt
                buf_items = []
            last_placed_end = frame + duration

        def place_and_buf(clip_obj, frame, duration):
            nonlocal success_count, buf_items, last_placed_end
            if SKIP_OCCUPIED_RANGES and in_skip_zone(frame, duration):
                return
            # 隙間があれば埋める
            fill_gap_if_needed(frame)
            # クリップ種類を特定してログ
            clip_name = getattr(clip_obj, "GetName", lambda: "unknown")()
            clip_type = "talk" if "talk" in clip_name.lower() else ("blink" if "blink" in clip_name.lower() else "normal")
            print(f"[DEBUG] 配置: {clip_type} {frame}-{frame+duration} ({frame_to_tc(frame)}-{frame_to_tc(frame+duration)}) [{clip_name}] dur={duration}")
            if push_item(buf_items, clip_obj, frame, duration):
                cnt = flush_buffer(buf_items)
                if cnt >= 0: success_count += cnt
                buf_items = []
            # 配置予定の終端を更新（バッファ flush 時に実際に配置される）
            last_placed_end = frame + duration

        def has_audio_at(block_idx):
            bs = OFFSET_FRAME + block_idx * BLOCK_FRAMES
            be = bs + BLOCK_FRAMES
            for s, e in talk_valid_ranges:
                if not (e <= bs or s >= be):
                    return True
            return False

        def check_pattern(offset, pattern):
            for pi, expected in enumerate(pattern):
                if block_states[offset + pi] != expected:
                    return False
            return True

        while bi < total_blocks:
            # 停止フラグ
            flag = check_stop_flag()
            if flag:
                print(f"[STOP] 停止フラグを検出: {flag}")
                stopped = True
                if buf_items:
                    cnt = flush_buffer(buf_items)
                    if cnt >= 0: success_count += cnt
                    buf_items = []
                break

            # 進捗
            total_range = timeline_end - OFFSET_FRAME
            done = bi * BLOCK_FRAMES
            cur_frame = OFFSET_FRAME + done
            progress = 100 * done // total_range if total_range else 0
            if progress > progress_last:
                progress_last = progress
                print(f"[PROGRESS] {progress}% ({done}/{total_range}) 経過:{time.time()-start_time:.1f}秒")

            state = block_states[bi]
            block_frame = OFFSET_FRAME + bi * BLOCK_FRAMES

            # スキップゾーン内のブロック → 単独スキップ
            if skip_blocks[bi]:
                print(f"[DEBUG] スキップ: block {bi} {block_frame}-{block_frame+BLOCK_FRAMES} ({frame_to_tc(block_frame)}-{frame_to_tc(block_frame+BLOCK_FRAMES)})")
                total_placed_frames += BLOCK_FRAMES
                bi += 1
                continue

            # ----------------------------------------------------------------
            # まばたき: 常に10f単独
            # ----------------------------------------------------------------
            if state == "blink":
                place_and_buf(get_clip(blink_clip, blink_clip_trans), block_frame, BLOCK_FRAMES)
                total_placed_frames += BLOCK_FRAMES
                bi += 1
                continue

            # ----------------------------------------------------------------
            # 音声区間（talk / normal-in-talk の交互パターン）
            # ----------------------------------------------------------------
            if has_audio_at(bi):
                # 音声区間の連続長を数える
                seg_len = 0
                while bi + seg_len < total_blocks and has_audio_at(bi + seg_len):
                    if block_states[bi + seg_len] == "blink" or skip_blocks[bi + seg_len]:
                        break
                    seg_len += 1
                if seg_len < 1:
                    bi += 1
                    continue

                # 6ブロック → 60f
                if max_block_level >= 6:
                    while seg_len >= 6:
                        if check_pattern(bi, ["talk","normal","talk","normal","talk","normal"]):
                            place_and_buf(get_clip(talk_60f_a, talk_60f_a_trans), block_frame, BLOCK_FRAMES * 6)
                            total_placed_frames += BLOCK_FRAMES * 6
                            block_frame += BLOCK_FRAMES * 6; bi += 6; seg_len -= 6
                            continue
                        if check_pattern(bi, ["normal","talk","normal","talk","normal","talk"]):
                            place_and_buf(get_clip(talk_60f_b, talk_60f_b_trans), block_frame, BLOCK_FRAMES * 6)
                            total_placed_frames += BLOCK_FRAMES * 6
                            block_frame += BLOCK_FRAMES * 6; bi += 6; seg_len -= 6
                            continue
                        break

                # 3ブロック → 30f
                while seg_len >= 3:
                    p0 = block_states[bi]
                    p1 = block_states[bi + 1]
                    p2 = block_states[bi + 2]
                    if p0 == "blink" or p1 == "blink" or p2 == "blink":
                        break
                    if p0 == "talk" and p1 == "normal" and p2 == "talk":
                        place_and_buf(get_clip(talk_30f_a, talk_30f_a_trans), block_frame, BLOCK_FRAMES * 3)
                        total_placed_frames += BLOCK_FRAMES * 3
                        block_frame += BLOCK_FRAMES * 3; bi += 3; seg_len -= 3
                        continue
                    if p0 == "normal" and p1 == "talk" and p2 == "normal":
                        place_and_buf(get_clip(talk_30f_b, talk_30f_b_trans), block_frame, BLOCK_FRAMES * 3)
                        total_placed_frames += BLOCK_FRAMES * 3
                        block_frame += BLOCK_FRAMES * 3; bi += 3; seg_len -= 3
                        continue
                    break

                # 残りは10f単位
                while seg_len >= 1:
                    base_clip = talk_clip if block_states[bi] == "talk" else normal_clip
                    trans_clip = talk_clip_trans if block_states[bi] == "talk" else normal_clip_trans
                    place_and_buf(get_clip(base_clip, trans_clip), block_frame, BLOCK_FRAMES)
                    total_placed_frames += BLOCK_FRAMES
                    block_frame += BLOCK_FRAMES; bi += 1; seg_len -= 1

            # ----------------------------------------------------------------
            # 無音区間（通常状態、まばたきを除く）
            # ----------------------------------------------------------------
            else:
                norm_len = 0
                while bi + norm_len < total_blocks:
                    s = block_states[bi + norm_len]
                    if s != "normal" or skip_blocks[bi + norm_len]:
                        break
                    norm_len += 1
                if norm_len < 1:
                    bi += 1
                    continue

                # 60f優先 → 30f → 10f
                if max_block_level >= 6:
                    while norm_len >= 6:
                        place_and_buf(get_clip(normal_60f, normal_60f_trans), block_frame, BLOCK_FRAMES * 6)
                        total_placed_frames += BLOCK_FRAMES * 6
                        block_frame += BLOCK_FRAMES * 6; bi += 6; norm_len -= 6
                while norm_len >= 3:
                    place_and_buf(get_clip(normal_30f, normal_30f_trans), block_frame, BLOCK_FRAMES * 3)
                    total_placed_frames += BLOCK_FRAMES * 3
                    block_frame += BLOCK_FRAMES * 3; bi += 3; norm_len -= 3
                while norm_len >= 1:
                    place_and_buf(get_clip(normal_clip, normal_clip_trans), block_frame, BLOCK_FRAMES)
                    total_placed_frames += BLOCK_FRAMES
                    block_frame += BLOCK_FRAMES; bi += 1; norm_len -= 1

        # バッファフラッシュ
        if buf_items:
            cnt = flush_buffer(buf_items)
            if cnt >= 0: success_count += cnt
            buf_items = []

        # スキップゾーン境界の端数隙間を埋める（1-9f）— raw位置（実プレースホルダー位置）で判定
        if SKIP_OCCUPIED_RANGES and skip_raw_ranges:
            try:
                final_items = sorted(timeline.GetItemListInTrack("video", VIDEO_TRACK) or [], key=lambda x: x.GetStart())
                for s_raw, e_raw in skip_raw_ranges:
                    # 前側端数: ゾーン直前の配置クリップと 実プレースホルダー開始(s_raw) の間
                    prev_items = [it for it in final_items if it.GetEnd() <= s_raw]
                    if prev_items:
                        last_end = max(it.GetEnd() for it in prev_items)
                        gap = s_raw - last_end
                        if 0 < gap < BLOCK_FRAMES:
                            print(f"[DEBUG] スキップ前端数埋め: {last_end}-{s_raw} gap={gap}f")
                            place_short_normal(last_end, gap)
                            final_items = sorted(timeline.GetItemListInTrack("video", VIDEO_TRACK) or [], key=lambda x: x.GetStart())
                    # 後側端数: 実プレースホルダー終了(e_raw) と次の配置クリップの間
                    next_items = [it for it in final_items if it.GetStart() >= e_raw]
                    if next_items:
                        next_start = min(it.GetStart() for it in next_items)
                        gap = next_start - e_raw
                        if 0 < gap < BLOCK_FRAMES:
                            print(f"[DEBUG] スキップ後端数埋め: {e_raw}-{next_start} gap={gap}f")
                            place_short_normal(e_raw, gap)
                            final_items = sorted(timeline.GetItemListInTrack("video", VIDEO_TRACK) or [], key=lambda x: x.GetStart())
            except Exception as ex:
                print(f"[INFO] スキップ境界端数埋めスキップ: {ex}")

        # 隙間埋めバッファをフラッシュ
        if buf_items:
            cnt = flush_buffer(buf_items)
            if cnt >= 0: success_count += cnt
            buf_items = []

        success_count = total_placed_frames // BLOCK_FRAMES

    # 隙間検証（配置後トラックを読み戻して確認）
    if SKIP_OCCUPIED_RANGES and skip_ranges:
        try:
            final_items = sorted(timeline.GetItemListInTrack("video", VIDEO_TRACK) or [], key=lambda x: x.GetStart())
            gaps = []
            prev_end = OFFSET_FRAME
            for item in final_items:
                s = item.GetStart()
                e = item.GetEnd()
                if s > prev_end:
                    in_skip_only = all(
                        any(sr <= f < er for sr, er in skip_ranges)
                        for f in range(prev_end, min(s, prev_end + 2000))
                    )
                    if not in_skip_only:
                        gaps.append((prev_end, s))
                prev_end = max(prev_end, e)
            if gaps:
                gap_frames = sum(e - s for s, e in gaps)
                print(f"[WARNING] 隙間が {len(gaps)} 箇所 ({gap_frames}f) 見つかりました")
                for s, e in gaps[:5]:
                    print(f"          フレーム {s}-{e} ({e-s}f)")
            else:
                print(f"[INFO] 隙間なし（全フレーム配置済み）")
        except Exception as ex:
            print(f"[INFO] 隙間検証スキップ: {ex}")

    elapsed = time.time() - start_time
    print("=" * 60)
    if stopped:
        print(f"[STOP] ユーザーにより中断されました。")
    else:
        print(f"[SUCCESS] 処理が正常に完了しました！")
    print(f"          配置ブロック数: {success_count} (計 {success_count * BLOCK_FRAMES} フレーム)")
    print(f"          処理時間: {elapsed:.1f}秒")
    print("=" * 60)

if __name__ == "__main__":
    main()