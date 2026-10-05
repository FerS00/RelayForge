from __future__ import annotations

import ipaddress
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(ValueError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, env_prefix="RELAYFORGE_", env_file=None)

    workspace_dir: Path
    projects_root: Path
    port: int
    home: Path
    claude_executable: str
    claude_model: str = ""
    codex_executable: str = "codex"
    agent_models: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @field_validator("agent_models")
    @classmethod
    def validate_models(cls, value: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        if set(value) - {"claude", "codex", "antigravity"}:
            raise ValueError("Agente no válido en el catálogo de modelos.")
        if any(
            len(model) > 128 or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", model) is None
            for models in value.values()
            for model in models
        ):
            raise ValueError("Identificador de modelo no válido.")
        return value

    bind: str = "127.0.0.1"
    container_mode: bool = False
    trusted_proxy_ip: str = ""
    allowed_tailscale_logins: tuple[str, ...] = ()
    allowed_hosts: tuple[str, ...] = ()


def load_settings(**overrides: Any) -> Settings:
    configured_home = overrides.get("home") or os.environ.get("RELAYFORGE_HOME")
    if configured_home:
        home = Path(configured_home).expanduser().resolve()
    else:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise SettingsError("No se pudo determinar el directorio de datos local.")
        home = (Path(local_app_data) / "RelayForge").expanduser().resolve()
    configured_projects_root = overrides.get("projects_root") or os.environ.get("RELAYFORGE_PROJECTS_ROOT")
    projects_root = (
        Path(configured_projects_root).expanduser().resolve()
        if configured_projects_root
        else (home / "projects").resolve()
    )
    values: dict[str, Any] = {
        "workspace_dir": None,
        "port": 8787,
        "home": home,
        "claude_executable": "claude",
        "claude_model": "",
        "codex_executable": "codex",
        "agent_models": {},
        "projects_root": projects_root,
        "bind": "127.0.0.1",
        "container_mode": False,
        "trusted_proxy_ip": "",
        "allowed_tailscale_logins": (),
        "allowed_hosts": (),
    }
    config_path = home / "config" / "settings.yaml"
    if config_path.is_file():
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            raise SettingsError("No se pudo leer la configuración.") from None
        if not isinstance(config, dict):
            raise SettingsError("La configuración debe ser un objeto YAML.")
        allowed = {
            "workspace_dir",
            "projects_root",
            "port",
            "claude_executable",
            "claude_model",
            "codex_executable",
            "agent_models",
            "bind",
            "trusted_proxy_ip",
            "allowed_tailscale_logins",
            "allowed_hosts",
        }
        values.update({key: value for key, value in config.items() if key in allowed})
    names = {
        "workspace_dir": "RELAYFORGE_WORKSPACE_DIR",
        "port": "RELAYFORGE_PORT",
        "claude_executable": "RELAYFORGE_CLAUDE_BIN",
        "claude_model": "RELAYFORGE_CLAUDE_MODEL",
        "codex_executable": "RELAYFORGE_CODEX_BIN",
        "projects_root": "RELAYFORGE_PROJECTS_ROOT",
        "bind": "RELAYFORGE_BIND",
        "container_mode": "RELAYFORGE_CONTAINER_MODE",
        "trusted_proxy_ip": "RELAYFORGE_TRUSTED_PROXY_IP",
        "allowed_tailscale_logins": "RELAYFORGE_ALLOWED_TAILSCALE_LOGINS",
        "allowed_hosts": "RELAYFORGE_ALLOWED_HOSTS",
    }
    for key, env_name in names.items():
        if env_name in os.environ:
            values[key] = os.environ[env_name]
    values.update({key: value for key, value in overrides.items() if key in values})
    if "RELAYFORGE_AGENT_MODELS" in os.environ:
        try:
            values["agent_models"] = json.loads(os.environ["RELAYFORGE_AGENT_MODELS"])
        except json.JSONDecodeError:
            raise SettingsError("RELAYFORGE_AGENT_MODELS debe ser un objeto JSON.") from None
    try:
        projects_root = Path(values["projects_root"]).expanduser().resolve()
    except (OSError, TypeError):
        raise SettingsError("RELAYFORGE_PROJECTS_ROOT no es una ruta válida.") from None
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
    container_raw = values["container_mode"]
    if isinstance(container_raw, bool):
        container_mode = container_raw
    elif str(container_raw).strip().lower() in {"1", "true", "yes"}:
        container_mode = True
    elif str(container_raw).strip().lower() in {"0", "false", "no", ""}:
        container_mode = False
    else:
        raise SettingsError("RELAYFORGE_CONTAINER_MODE debe ser booleano.")
    bind = str(values["bind"])
    trusted_proxy_ip = str(values["trusted_proxy_ip"] or "").strip()
    if container_mode:
        if os.name != "nt":
            raise SettingsError("El modo contenedor de RelayForge requiere Windows.")
        if bind != "0.0.0.0":
            raise SettingsError("RELAYFORGE_BIND debe ser 0.0.0.0 en modo contenedor.")
        try:
            proxy_address = ipaddress.ip_address(trusted_proxy_ip)
        except ValueError:
            raise SettingsError("RELAYFORGE_TRUSTED_PROXY_IP debe ser una IP exacta.") from None
        if (
            proxy_address.version != 4
            or proxy_address.is_loopback
            or proxy_address.is_unspecified
            or proxy_address.is_multicast
        ):
            raise SettingsError("RELAYFORGE_TRUSTED_PROXY_IP debe ser una IP IPv4 unicast no-loopback.")
    elif bind != "127.0.0.1" or trusted_proxy_ip:
        raise SettingsError("RELAYFORGE_BIND solo admite 127.0.0.1 fuera del modo contenedor.")

    def parse_allowlist(value: Any, label: str, *, hosts: bool = False) -> tuple[str, ...]:
        if isinstance(value, str):
            if value.lstrip().startswith("["):
                try:
                    decoded = json.loads(value)
                except json.JSONDecodeError:
                    raise SettingsError(f"{label} debe ser una lista JSON válida.") from None
                if not isinstance(decoded, list):
                    raise SettingsError(f"{label} debe ser una lista JSON.")
                entries = decoded
            else:
                entries = value.split(",")
        elif isinstance(value, (list, tuple)):
            entries = list(value)
        else:
            raise SettingsError(f"{label} debe ser una lista separada por comas.")
        normalized: list[str] = []
        for entry in entries:
            item = str(entry).strip().lower().rstrip(".")
            if not item:
                continue
            if "*" in item or "/" in item or (hosts and "@" in item):
                raise SettingsError(f"{label} solo admite valores exactos.")
            if hosts:
                label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                if len(item) > 253 or re.fullmatch(rf"{label}(?:\.{label})*", item) is None:
                    raise SettingsError("RELAYFORGE_ALLOWED_HOSTS contiene un host inválido.")
            elif re.fullmatch(r"[a-z0-9_.+-]+@[a-z0-9.-]+", item) is None:
                raise SettingsError("RELAYFORGE_ALLOWED_TAILSCALE_LOGINS contiene un login inválido.")
            if item not in normalized:
                normalized.append(item)
        return tuple(normalized)

    allowed_logins = parse_allowlist(
        values["allowed_tailscale_logins"], "RELAYFORGE_ALLOWED_TAILSCALE_LOGINS"
    )
    allowed_hosts = parse_allowlist(values["allowed_hosts"], "RELAYFORGE_ALLOWED_HOSTS", hosts=True)
    claude_model = str(values["claude_model"] or "")
    if claude_model and re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", claude_model) is None:
        raise SettingsError("El modelo de Claude contiene caracteres no permitidos.")
    return Settings(
        workspace_dir=workspace,
        port=port,
        home=home,
        projects_root=projects_root,
        claude_executable=str(values["claude_executable"]),
        claude_model=claude_model,
        codex_executable=str(values["codex_executable"]),
        bind=str(values["bind"]),
        container_mode=container_mode,
        trusted_proxy_ip=trusted_proxy_ip,
        allowed_tailscale_logins=allowed_logins,
        allowed_hosts=allowed_hosts,
    )
