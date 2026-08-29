import os
import json
import re

# ==============================================================================
# タイミング連番PNG 配置スクリプト（Step3）
# ==============================================================================
# 使用方法:
# 1. 「タイミングJSONから連番生成」で出力した timing_output フォルダを
#    Resolveのメディアプールに手動ドラッグ＆ドロップ（連番PNGとして認識されます）
# 2. このスクリプトを実行
# 3. タイムラインに配置されます
# ==============================================================================

TIMING_JSON = "timing.json"
SEQUENCE_FOLDER = "timing_output"
CLIP_NAME_PREFIX = "output_"
VIDEO_TRACK = 2

def find_clip_in_pool(folder, name_hint):
    """メディアプールから該当するシーケンスクリップを検索"""
    for clip in folder.GetClipList():
        clip_name = clip.GetName()
        if name_hint in clip_name:
            return clip
    for sub in folder.GetSubFolderList():
        result = find_clip_in_pool(sub, name_hint)
        if result:
            return result
    return None

def parse_timecode(tc_str, fps):
    if not tc_str or not isinstance(tc_str, str):
        return 0
    parts = tc_str.split(":")
    if len(parts) == 4:
        try:
            return int(parts[0]) * 3600 * fps + int(parts[1]) * 60 * fps + int(parts[2]) * fps + int(parts[3])
        except ValueError:
            return 0
    return 0

def main():
    print("=" * 60)
    print(" タイミング連番PNG 配置 (Step3)")
    print("=" * 60)

    try:
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject()
        if not project:
            print("[ERROR] プロジェクトが見つかりません")
            return
        timeline = project.GetCurrentTimeline()
        if not timeline:
            print("[ERROR] タイムラインが見つかりません")
            return
        media_pool = project.GetMediaPool()
        root = media_pool.GetRootFolder()
    except NameError:
        print("[ERROR] Resolve環境で実行してください")
        return

    # FPS検出
    try:
        fps_raw = project.GetSetting("timelineFrameRate")
        match = re.search(r"([\d.]+)", str(fps_raw))
        FPS = float(match.group(1)) if match else 60.0
        FPS = round(FPS)
    except:
        FPS = 60

    # timing.json を読み込み
    json_path = os.path.join(os.getcwd(), TIMING_JSON)
    if not os.path.exists(json_path):
        print(f"[ERROR] {TIMING_JSON} が見つかりません。Step1を先に実行してください。")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        timing = json.load(f)

    offset_frame = timing.get("offset_frame", 0)
    total_frames = timing.get("total_frames", 0)

    # 開始タイムコード補正
    try:
        tc = timeline.GetStartTimecode()
        start_offset = parse_timecode(tc, FPS)
        if offset_frame < start_offset:
            offset_frame = start_offset
    except:
        pass

    print(f"[INFO] total_frames: {total_frames}")
    print(f"[INFO] offset_frame: {offset_frame}")

    # メディアプールからクリップ検索
    clip = find_clip_in_pool(root, CLIP_NAME_PREFIX)
    if not clip:
        print(f"[WARN] '{CLIP_NAME_PREFIX}' を含むクリップが見つかりません")
        print("[INFO] timing_output フォルダをメディアプールにドラッグしてから再実行してください")
        return

    clip_name = clip.GetName()
    clip_duration = clip.GetFrames() if hasattr(clip, "GetFrames") else total_frames
    print(f"[INFO] 検出クリップ: {clip_name} ({clip_duration}f)")

    # トラッククリア
    items = timeline.GetItemListInTrack("video", VIDEO_TRACK)
    if items:
        timeline.DeleteClips(items)
        print(f"[INFO] Video トラック{VIDEO_TRACK} をクリアしました")

    # 配置
    result = media_pool.AppendToTimeline([{
        "mediaPoolItem": clip,
        "startFrame": 0,
        "endFrame": total_frames,
        "recordFrame": offset_frame,
        "trackIndex": VIDEO_TRACK
    }])

    if not result:
        print("[ERROR] 配置に失敗しました")
        return

    # 変形プロパティを設定（既存クリップから継承）
    new_clip = result[0]
    try:
        new_clip.SetProperty("Pan", 0.0)
        new_clip.SetProperty("Tilt", 0.0)
        new_clip.SetProperty("ZoomX", 1.0)
        new_clip.SetProperty("ZoomY", 1.0)
    except Exception as e:
        print(f"[WARN] SetProperty失敗: {e}")

    print(f"[SUCCESS] 配置完了: {offset_frame}f に {total_frames}f のクリップ ({total_frames/FPS:.1f}秒)")

if __name__ == "__main__":
    main()
