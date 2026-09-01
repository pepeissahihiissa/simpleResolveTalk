"""character_lip_sync.py のパース・自動検索ロジックのテスト（Resolveなし）。"""
# -*- coding: utf-8 -*-
import os

import pytest

import character_lip_sync as cl


class MockClip:
    def __init__(self, name, path=None):
        self._name = name
        self._path = path

    def GetName(self):
        return self._name

    def GetClipProperty(self, key):
        return self._path if key == "File Path" else None


class MockFolder:
    def __init__(self, clips, subfolders=None):
        self._clips = clips
        self._subs = subfolders or []

    def GetClipList(self):
        return self._clips

    def GetSubFolderList(self):
        return self._subs


# ---------------------------------------------------------------------------
# parse_timecode
# ---------------------------------------------------------------------------
def test_parse_timecode_basic():
    assert cl.parse_timecode("00:00:00:00", 60) == 0
    assert cl.parse_timecode("00:00:01:00", 60) == 60
    assert cl.parse_timecode("01:00:00:00", 60) == 216000
    assert cl.parse_timecode("00:00:05:00", 60) == 300


def test_parse_timecode_invalid():
    assert cl.parse_timecode("", 60) == 0
    assert cl.parse_timecode(None, 60) == 0
    assert cl.parse_timecode("abc", 60) == 0
    assert cl.parse_timecode("1:2:3", 60) == 0


# ---------------------------------------------------------------------------
# parse_new_clip_name（クリップ名に全情報が入っている.）
# ---------------------------------------------------------------------------
def test_parse_new_clip_name_full():
    info = cl.parse_new_clip_name("もち子_2_1_normal_[0000-0009].png")
    assert info == {
        "id": "もち子", "video_track": 2, "audio_track": 1,
        "state": "normal", "frames": 10,
    }


def test_parse_new_clip_name_wide_range():
    info = cl.parse_new_clip_name("A_1_1_talk_a_[0000-0059].png")
    assert info == {
        "id": "A", "video_track": 1, "audio_track": 1,
        "state": "talk_a", "frames": 60,
    }


def test_parse_new_clip_name_invalid():
    assert cl.parse_new_clip_name("normal_[0000-0009].png") is None
    assert cl.parse_new_clip_name("character_lip_sync.py") is None
    assert cl.parse_new_clip_name("") is None


# ---------------------------------------------------------------------------
# parse_new_folder_name（フォルダごとドロップ時のフォルダ名.）
# ---------------------------------------------------------------------------
def test_parse_new_folder_name_basic():
    info = cl.parse_new_folder_name("もち子_2_1_normal_10")
    assert info == {
        "id": "もち子", "video_track": 2, "audio_track": 1,
        "state": "normal", "frames": 10,
    }


def test_parse_new_folder_name_utf8_usagi():
    info = cl.parse_new_folder_name("usagi_3_2_talk_b_60")
    assert info == {
        "id": "usagi", "video_track": 3, "audio_track": 2,
        "state": "talk_b", "frames": 60,
    }


# ---------------------------------------------------------------------------
# get_clip_source_info（クリップ名→フォルダ名のフォールバック復元.）
# ---------------------------------------------------------------------------
def test_source_info_from_clip_name_takes_precedence():
    c = MockClip("A_1_1_normal_[0000-0009].png", r"K:\other\folder\whatever\nothing_9_9.png")
    info = cl.get_clip_source_info(c)
    assert info["id"] == "A" and info["video_track"] == 1 and info["state"] == "normal"


def test_source_info_from_folder_path_file_inside():
    c = MockClip(
        "normal_[0000-0009].png",
        r"K:\movie\簡易口パク\もち子_2_1_normal_10\normal_0000.png",
    )
    info = cl.get_clip_source_info(c)
    assert info["id"] == "もち子"
    assert info["video_track"] == 2 and info["audio_track"] == 1
    assert info["state"] == "normal" and info["frames"] == 10


def test_source_info_from_folder_path_dir_only():
    c = MockClip("blink_[0000-0009].png", r"C:\설to\バニー_3_2_talk_10")
    info = cl.get_clip_source_info(c)
    assert info["id"] == "バニー"
    assert info["video_track"] == 3 and info["audio_track"] == 2
    assert info["state"] == "talk" and info["frames"] == 10


def test_source_info_from_mixed_separators():
    c = MockClip("blink_[0000-0009].png", "K:/簡易口パク/モチ子_2_1_blink_10/blink_0000.png")
    info = cl.get_clip_source_info(c)
    assert info["id"] == "モチ子" and info["frames"] == 10


def test_source_info_no_path_no_match():
    c = MockClip("normal_[0000-0009].png", None)
    assert cl.get_clip_source_info(c) is None
    c2 = MockClip("normal_[0000-0009].png", r"C:\data\misc\normal_0000.png")
    assert cl.get_clip_source_info(c2) is None


# ---------------------------------------------------------------------------
# auto_search_characters（同一クリップ名でもフォルダパスで区別.）
# ---------------------------------------------------------------------------
def test_auto_search_disambiguates_identical_clip_names():
    clips = [
        MockClip("normal_[0000-0009].png", r"K:\movie\もち子_2_1_normal_10\normal_0000.png"),
        MockClip("blink_[0000-0009].png", r"K:\movie\もち子_2_1_blink_10\blink_0000.png"),
        MockClip("talk_a_[0000-0029].png", r"K:\movie\もち子_2_1_talk_a_30\talk_a_0000.png"),
        MockClip("talk_b_[0000-0029].png", r"K:\movie\もち子_2_1_talk_b_30\talk_b_0000.png"),
        MockClip("normal_[0000-0059].png", r"K:\movie\A_1_1_normal_60\normal_0000.png"),
        MockClip("blink_[0000-0009].png", r"K:\movie\A_1_1_blink_10\blink_0000.png"),
        MockClip("talk_a_[0000-0059].png", r"K:\movie\A_1_1_talk_a_60\talk_a_0000.png"),
        MockClip("talk_b_[0000-0059].png", r"K:\movie\A_1_1_talk_b_60\talk_b_0000.png"),
    ]
    root = MockFolder(clips)
    chars, skipped = cl.auto_search_characters(root)

    assert skipped is False
    assert set(chars.keys()) == {"もち子", "A"}

    m = chars["もち子"]
    assert m["video_track"] == 2 and m["audio_track"] == 1
    assert set(m["clips"].keys()) == {"normal_10", "blink_10", "talk_a_30", "talk_b_30"}

    a = chars["A"]
    assert a["video_track"] == 1 and a["audio_track"] == 1
    assert set(a["clips"].keys()) == {"normal_60", "blink_10", "talk_a_60", "talk_b_60"}


def test_auto_search_skips_unrelated_clips():
    clips = [
        MockClip("normal_[0000-0009].png", r"K:\movie\もち子_2_1_normal_10\normal_0000.png"),
        MockClip("video.mov", r"K:\movie\project\video.mov"),
        MockClip("audio.wav", r"K:\movie\project\audio.wav"),
    ]
    root = MockFolder(clips)
    chars, skipped = cl.auto_search_characters(root)
    assert set(chars.keys()) == {"もち子"}
    assert skipped is True


def test_auto_search_recurses_subfolders():
    leaf = MockFolder([
        MockClip("normal_[0000-0009].png", r"K:\movie\もち子_2_1_normal_10\normal_0000.png"),
    ])
    root = MockFolder([], subfolders=[MockFolder([], subfolders=[leaf])])
    chars, _ = cl.auto_search_characters(root)
    assert set(chars.keys()) == {"もち子"}


# ---------------------------------------------------------------------------
# 出力フォルダ名（GUIと揃っているか）
# ---------------------------------------------------------------------------
def test_folder_convention_matches_gui():
    # GUI側 FOLDER_DEFS と同形式（正規表現で受理できる）ことを確認
    folders = [
        "もち子_2_1_normal_10", "もち子_2_1_blink_10", "もち子_2_1_talk_10",
        "もち子_2_1_normal_30", "もち子_2_1_talk_a_30", "もち子_2_1_talk_b_30",
        "もち子_2_1_normal_60", "もち子_2_1_talk_a_60", "もち子_2_1_talk_b_60",
    ]
    for name in folders:
        assert cl.parse_new_folder_name(name) is not None, name