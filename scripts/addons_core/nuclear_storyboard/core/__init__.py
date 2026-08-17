"""Nucleo do add-on: modelo, persistencia, timing e regras — tudo sem `bpy`.

Manter este pacote livre de `bpy` e proposital: da para rodar os testes no
Python do host e reaproveitar o mesmo codigo num worker headless depois.
"""

from .context import (DEFAULT_PROJECT_NAME, ROLE_BOARD, ROLE_EPISODE,
                      ROLE_SCENE, FolderContext, board_above, context_from_path,
                      dropbox_local_root, ensure_structure, episode_scenes,
                      find_shared_library, folder_role, is_stage_folder,
                      nested_boards, next_scene_number, path_from_link,
                      scene_folder_name, scene_folders, sibling_identity)
from .model import (SCHEMA_VERSION, Audio, BurnIn, Character, Drawing, Episode,
                    Library, Project, Prop, Scene, Settings, Take,
                    hex_from_rgb, normalize_hex, rgb_from_hex)
from .naming import (project_code, scope_basename, suggest_project_code,
                     take_basename, take_basename_by_id)
from .rules import Issue, blocks_export, validate_project, validate_take
from .split import SplitError, split_plan
from .storage import ProjectPaths, ProjectStore, StorageError
from .timing import build_timeline, distribute_exposures, take_duration

__all__ = [
    "DEFAULT_PROJECT_NAME", "ROLE_BOARD", "ROLE_EPISODE", "ROLE_SCENE",
    "FolderContext", "board_above", "context_from_path", "dropbox_local_root",
    "ensure_structure", "episode_scenes", "find_shared_library", "folder_role",
    "is_stage_folder", "nested_boards", "next_scene_number", "path_from_link",
    "scene_folder_name", "scene_folders", "sibling_identity",
    "SCHEMA_VERSION", "Audio", "BurnIn", "Character", "Drawing", "Episode",
    "Library", "Project", "Prop", "Scene", "Settings", "Take",
    "hex_from_rgb", "normalize_hex", "rgb_from_hex",
    "project_code", "scope_basename", "suggest_project_code", "take_basename",
    "take_basename_by_id",
    "Issue", "blocks_export", "validate_project", "validate_take",
    "SplitError", "split_plan",
    "ProjectPaths", "ProjectStore", "StorageError",
    "build_timeline", "distribute_exposures", "take_duration",
]
