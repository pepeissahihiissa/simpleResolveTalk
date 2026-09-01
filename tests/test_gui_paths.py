"""simpleTalkGui.py のパス解決ヘルパーのテスト（GUI起動なし）。"""
# -*- coding: utf-8 -*-
import os
import sys

import simpleTalkGui as gui


def test_app_dir_not_empty():
    assert isinstance(gui._app_dir(), str)
    assert os.path.isdir(gui._app_dir())


def test_config_path_is_absolute():
    p = gui._config_path()
    assert os.path.basename(p) == "config.json"
    assert os.path.dirname(p) == gui._app_dir()


def test_resolve_script_dir_search_returns_existing_or_default():
    d = gui._find_resolve_script_dir()
    assert isinstance(d, str)
    assert d.endswith("Scripts" + os.sep + "Utility") or d.endswith("Scripts/Utility")


def test_resolve_script_dir_candidates_are_expandable():
    for cand in gui.RESOLVE_SCRIPT_DIR_CANDIDATES:
        assert "%" not in os.path.expandvars(cand)


def test_log_file_suffix():
    assert gui.LOG_FILE.endswith(".log")


def test_script_name_bundled_constant():
    assert gui.RESOLVE_SCRIPT_NAME == "character_lip_sync.py"