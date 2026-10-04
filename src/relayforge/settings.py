from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(ValueError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, env_prefix="RELAYFORGE_", env_file=None)

    workspace_dir: Path
    port: int
    home: Path
    claude_executable: str
    claude_model: str = ""


def load_settings(**overrides: Any) -> Settings:
    configured_home = overrides.get("home") or os.environ.get("RELAYFORGE_HOME")
    if configured_home:
        home = Path(configured_home).expanduser().resolve()
    else:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise SettingsError("No se pudo determinar el directorio de datos local.")
        home = (Path(local_app_data) / "RelayForge").expanduser().resolve()
    values: dict[str, Any] = {
        "workspace_dir": None,
        "port": 8787,
        "home": home,
        "claude_executable": "claude",
        "claude_model": "",
    }
    config_path = home / "config" / "settings.yaml"
    if config_path.is_file():
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            raise SettingsError("No se pudo leer la configuración.") from None
        if not isinstance(config, dict):
            raise SettingsError("La configuración debe ser un objeto YAML.")
        allowed = {"workspace_dir", "port", "claude_executable", "claude_model"}
        values.update({key: value for key, value in config.items() if key in allowed})
    names = {
        "workspace_dir": "RELAYFORGE_WORKSPACE_DIR",
        "port": "RELAYFORGE_PORT",
        "claude_executable": "RELAYFORGE_CLAUDE_BIN",
        "claude_model": "RELAYFORGE_CLAUDE_MODEL",
    }
    for key, env_name in names.items():
        if env_name in os.environ:
            values[key] = os.environ[env_name]
    values.update({key: value for key, value in overrides.items() if key in values})
    if not values["workspace_dir"]:
        raise SettingsError("RELAYFORGE_WORKSPACE_DIR es obligatorio.")
    try:
        workspace = Path(values["workspace_dir"]).expanduser().resolve(strict=True)
    except (OSError, TypeError):
        raise SettingsError("El directorio de trabajo no existe.") from None
    if not workspace.is_dir():
        raise SettingsError("El directorio de trabajo no es un directorio.")
    try:
        port = int(values["port"])
    except (ValueError, TypeError):
        raise SettingsError("El puerto debe ser un entero entre 1024 y 65535.") from None
    if not 1024 <= port <= 65535:
        raise SettingsError("El puerto debe ser un entero entre 1024 y 65535.")
    claude_model = str(values["claude_model"] or "")
    if claude_model and re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", claude_model) is None:
        raise SettingsError("El modelo de Claude contiene caracteres no permitidos.")
    return Settings(
        workspace_dir=workspace,
        port=port,
        home=home,
        claude_executable=str(values["claude_executable"]),
        claude_model=claude_model,
    )
