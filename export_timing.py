import os
import json
import re

# ==============================================================================
# タイミング情報エクスポート（Step1）
# ==============================================================================
# 使用方法:
# 1. Resolveでプロジェクトとタイムラインを開く
# 2. このスクリプトを Scripts/Utility にコピー
# 3. Resolveメニュー → Workspace → Scripts → 実行
# 4. timing.json がカレントフォルダに出力される
# ==============================================================================
# 出力フォーマット:
#   {
#     "version": 1,
#     "fps": 60,
#     "offset_frame": 216000,
#     "total_frames": 42319,
#     "segments": [
#       {"start": 0, "end": 360, "state": "normal"},
#       {"start": 360, "end": 540, "state": "talk"},
#       ...
#     ]
#   }
# ==============================================================================

OUTPUT_FILE = "timing.json"
AUDIO_TRACK = 1
VIDEO_TRACK = 2

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
    print(" タイミング情報エクスポート (Step1)")
    print("=" * 60)

    # Resolve API初期化
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
    print(f"[INFO] フレームレート: {FPS}fps")

    # 開始タイムコード検出
    try:
        tc = timeline.GetStartTimecode()
        offset_frame = parse_timecode(tc, FPS)
        print(f"[INFO] 開始タイムコード: '{tc}' → {offset_frame}f")
    except:
        offset_frame = 0
        print(f"[INFO] 開始タイムコード検出失敗、0を使用")

    # オーディオアイテム取得
    audio_items = timeline.GetItemListInTrack("audio", AUDIO_TRACK)
    if not audio_items:
        print("[ERROR] オーディオトラックに音声がありません")
        return

    audio_items = sorted(audio_items, key=lambda item: item.GetStart())
    timeline_end = timeline.GetEndFrame()

    # コンテンツの開始フレームを決定
    if offset_frame > 0:
        content_start = offset_frame
    else:
        content_start = min(item.GetStart() for item in audio_items)

    total_frames = timeline_end - content_start
    print(f"[INFO] コンテンツ範囲: {content_start}f ~ {timeline_end}f ({total_frames}f)")

    # セグメント構築
    # まず無音（normal）区間を埋めた後、音声（talk）区間で上書き
    segments = []
    prev_end = 0

    for item in audio_items:
        start_rel = item.GetStart() - content_start
        end_rel = item.GetEnd() - content_start

        # 無音区間（直前の音声終了～今回の音声開始）
        if start_rel > prev_end:
            segments.append({
                "start": prev_end,
                "end": start_rel,
                "state": "normal"
            })

        # 音声区間
        segments.append({
            "start": start_rel,
            "end": end_rel,
            "state": "talk"
        })

        prev_end = end_rel

    # 末尾の無音区間
    if prev_end < total_frames:
        segments.append({
            "start": prev_end,
            "end": total_frames,
            "state": "normal"
        })

    # JSON出力
    output = {
        "version": 1,
        "fps": FPS,
        "offset_frame": content_start,
        "total_frames": total_frames,
        "segments": segments
    }

    output_path = os.path.join(os.getcwd(), OUTPUT_FILE)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"[INFO] 音声区間数: {sum(1 for s in segments if s['state'] == 'talk')}")
    print(f"[INFO] total_frames: {total_frames} ({total_frames / FPS:.1f}秒)")
    print(f"[SUCCESS] 出力完了: {output_path}")
    print("=" * 60)

if __name__ == "__main__":
    main()
