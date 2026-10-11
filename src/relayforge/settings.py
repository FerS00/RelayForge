from __future__ import annotations

import ipaddress
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class SettingsError(ValueError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, env_prefix="RELAYFORGE_", env_file=None)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # load_settings() already parses the environment with its own validation rules.
        return (init_settings,)

    workspace_dir: Path
    projects_root: Path
    port: int
    home: Path
    claude_executable: str
    claude_model: str = ""
    codex_executable: str = "codex"
    antigravity_audit_runner: Path | None = None
    chat_agent: Literal["claude", "codex"] = "codex"
    chat_model: str = Field(
        default="gpt-6-luna", max_length=128, pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9._:/-]*)?$"
    )
    chat_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    agent_models: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    preview_gateway_port: int = Field(default=8793, ge=1024, le=65535)
    preview_public_origin: str = ""
    preview_port_range: tuple[int, int] = (8900, 8999)
    preview_idle_seconds: int = Field(default=1800, ge=60, le=86400)
    preview_max_active: int = Field(default=3, ge=1, le=10)
    desktop_enabled: bool = True
    desktop_apps: dict[str, Path] = Field(default_factory=dict)
    desktop_allowed_dirs: tuple[Path, ...] = ()
    desktop_action_timeout: int = Field(default=30, ge=5, le=120)

    @field_validator("desktop_apps")
    @classmethod
    def validate_desktop_apps(cls, value: dict[str, Path]) -> dict[str, Path]:
        if len(value) > 32 or any(
            re.fullmatch(r"[a-z0-9_-]{1,32}", name) is None or not Path(path).is_absolute()
            for name, path in value.items()
        ):
            raise ValueError("DESKTOP_APPS requiere nombres simples y ejecutables absolutos.")
        return value

    @field_validator("desktop_allowed_dirs")
    @classmethod
    def validate_desktop_dirs(cls, value: tuple[Path, ...]) -> tuple[Path, ...]:
        if len(value) > 16 or any(not Path(path).is_absolute() for path in value):
            raise ValueError("DESKTOP_ALLOWED_DIRS requiere rutas absolutas.")
        return value

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

    @field_validator("preview_port_range", mode="before")
    @classmethod
    def parse_preview_port_range(cls, value: Any) -> tuple[int, int]:
        if isinstance(value, str):
            parts = value.split("-")
            if len(parts) != 2:
                raise ValueError("RELAYFORGE_PREVIEW_PORT_RANGE debe tener el formato 8900-8999.")
            value = parts
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("RELAYFORGE_PREVIEW_PORT_RANGE debe contener dos puertos.")
        try:
            start, end = (int(part) for part in value)
        except (TypeError, ValueError):
            raise ValueError("RELAYFORGE_PREVIEW_PORT_RANGE contiene un puerto inválido.") from None
        if not 1024 <= start <= end <= 65535:
            raise ValueError("RELAYFORGE_PREVIEW_PORT_RANGE debe estar entre 1024 y 65535.")
        return start, end

    @model_validator(mode="after")
    def validate_previews(self) -> Settings:
        start, end = self.preview_port_range
        if self.preview_gateway_port == self.port:
            raise ValueError("PREVIEW_GATEWAY_PORT debe ser distinto de PORT.")
        if start <= self.port <= end or start <= self.preview_gateway_port <= end:
            raise ValueError("PREVIEW_PORT_RANGE no puede incluir PORT ni PREVIEW_GATEWAY_PORT.")
        origin = self.preview_public_origin or f"http://127.0.0.1:{self.preview_gateway_port}"
        from urllib.parse import urlsplit

        try:
            parsed = urlsplit(origin)
            hostname = (parsed.hostname or "").lower().rstrip(".")
            public_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            raise ValueError("PREVIEW_PUBLIC_ORIGIN no es un origen válido.") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or hostname not in {"localhost", "127.0.0.1", *self.allowed_hosts}
            or public_port == self.port
        ):
            raise ValueError("PREVIEW_PUBLIC_ORIGIN debe ser un origen permitido con puerto distinto.")
        normalized = f"{parsed.scheme}://{hostname}"
        if parsed.port is not None:
            normalized += f":{parsed.port}"
        object.__setattr__(self, "preview_public_origin", normalized)
        return self

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
        "antigravity_audit_runner": None,
        "chat_agent": "codex",
        "chat_model": "gpt-6-luna",
        "chat_effort": "medium",
        "projects_root": projects_root,
        "bind": "127.0.0.1",
        "container_mode": False,
        "trusted_proxy_ip": "",
        "allowed_tailscale_logins": (),
        "allowed_hosts": (),
        "preview_gateway_port": 8793,
        "preview_public_origin": "",
        "preview_port_range": (8900, 8999),
        "preview_idle_seconds": 1800,
        "preview_max_active": 3,
        "desktop_enabled": True,
        "desktop_apps": {},
        "desktop_allowed_dirs": (),
        "desktop_action_timeout": 30,
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
            "antigravity_audit_runner",
            "chat_agent",
            "chat_model",
            "chat_effort",
            "bind",
            "trusted_proxy_ip",
            "allowed_tailscale_logins",
            "allowed_hosts",
            "preview_gateway_port",
            "preview_public_origin",
            "preview_port_range",
            "preview_idle_seconds",
            "preview_max_active",
            "desktop_enabled",
            "desktop_apps",
            "desktop_allowed_dirs",
            "desktop_action_timeout",
        }
        values.update({key: value for key, value in config.items() if key in allowed})
    names = {
        "workspace_dir": "RELAYFORGE_WORKSPACE_DIR",
        "port": "RELAYFORGE_PORT",
        "claude_executable": "RELAYFORGE_CLAUDE_BIN",
        "claude_model": "RELAYFORGE_CLAUDE_MODEL",
        "codex_executable": "RELAYFORGE_CODEX_BIN",
        "antigravity_audit_runner": "RELAYFORGE_ANTIGRAVITY_AUDIT_RUNNER",
        "chat_agent": "RELAYFORGE_CHAT_AGENT",
        "chat_model": "RELAYFORGE_CHAT_MODEL",
        "chat_effort": "RELAYFORGE_CHAT_EFFORT",
        "projects_root": "RELAYFORGE_PROJECTS_ROOT",
        "bind": "RELAYFORGE_BIND",
        "container_mode": "RELAYFORGE_CONTAINER_MODE",
        "trusted_proxy_ip": "RELAYFORGE_TRUSTED_PROXY_IP",
        "allowed_tailscale_logins": "RELAYFORGE_ALLOWED_TAILSCALE_LOGINS",
        "allowed_hosts": "RELAYFORGE_ALLOWED_HOSTS",
        "preview_gateway_port": "RELAYFORGE_PREVIEW_GATEWAY_PORT",
        "preview_public_origin": "RELAYFORGE_PREVIEW_PUBLIC_ORIGIN",
        "preview_port_range": "RELAYFORGE_PREVIEW_PORT_RANGE",
        "preview_idle_seconds": "RELAYFORGE_PREVIEW_IDLE_SECONDS",
        "preview_max_active": "RELAYFORGE_PREVIEW_MAX_ACTIVE",
        "desktop_enabled": "RELAYFORGE_DESKTOP_ENABLED",
        "desktop_action_timeout": "RELAYFORGE_DESKTOP_ACTION_TIMEOUT",
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

    for key, env_name in (
        ("desktop_apps", "RELAYFORGE_DESKTOP_APPS"),
        ("desktop_allowed_dirs", "RELAYFORGE_DESKTOP_ALLOWED_DIRS"),
    ):
        if env_name in os.environ:
            try:
                values[key] = json.loads(os.environ[env_name])
            except json.JSONDecodeError:
                raise SettingsError(f"{env_name} debe ser JSON.") from None
    desktop_raw = values["desktop_enabled"]
    if isinstance(desktop_raw, bool):
        desktop_enabled = desktop_raw
    elif str(desktop_raw).strip().lower() in {"1", "true", "yes"}:
        desktop_enabled = True
    elif str(desktop_raw).strip().lower() in {"0", "false", "no"}:
        desktop_enabled = False
    else:
        raise SettingsError("RELAYFORGE_DESKTOP_ENABLED debe ser booleano.")
    if not isinstance(values["desktop_apps"], dict) or not isinstance(
        values["desktop_allowed_dirs"], (list, tuple)
    ):
        raise SettingsError("DESKTOP_APPS debe ser un objeto y DESKTOP_ALLOWED_DIRS una lista.")
    desktop_apps = {str(name): Path(str(path)) for name, path in values["desktop_apps"].items()}
    desktop_dirs = tuple(Path(str(path)).expanduser() for path in values["desktop_allowed_dirs"])
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
        antigravity_audit_runner=values["antigravity_audit_runner"],
        chat_agent=values["chat_agent"],
        chat_model=values["chat_model"],
        chat_effort=values["chat_effort"],
        agent_models=values["agent_models"],
        bind=str(values["bind"]),
        container_mode=container_mode,
        trusted_proxy_ip=trusted_proxy_ip,
        allowed_tailscale_logins=allowed_logins,
        allowed_hosts=allowed_hosts,
        preview_gateway_port=int(values["preview_gateway_port"]),
        preview_public_origin=str(values["preview_public_origin"] or ""),
        preview_port_range=values["preview_port_range"],
        preview_idle_seconds=int(values["preview_idle_seconds"]),
        preview_max_active=int(values["preview_max_active"]),
        desktop_enabled=desktop_enabled and not container_mode,
        desktop_apps=desktop_apps,
        desktop_allowed_dirs=desktop_dirs,
        desktop_action_timeout=int(values["desktop_action_timeout"]),
    )
