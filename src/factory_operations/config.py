"""설정 로딩 (docs/spec/01-core.md 4절, 07-runtime.md 1절).

순서: 기본 파일(`FOPS_DEFAULT_CONFIG`, 없으면 저장소 `config/default.yaml`)
→ overlay(`FOPS_CONFIG`) 깊은 병합 → 환경 변수 → pydantic 검증(`extra="forbid"`).
모르는 키·형식 오류·범위 밖 값은 키 경로를 담은 `ConfigError`가 되고,
`load_or_exit`는 그 메시지를 stderr에 쓰고 종료 코드 2로 끝낸다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "default.yaml"
EXIT_CONFIG_ERROR = 2

# 환경 변수 → 설정 키 (07-runtime.md 1절)
ENV_KEYS: dict[str, tuple[str, str]] = {
    "HTTP_HOST": ("http", "host"),
    "HTTP_PORT": ("http", "port"),
    "MQTT_URL": ("mqtt", "url"),
    "TOPIC_PREFIX": ("mqtt", "topic_prefix"),
    "DATABASE_URL": ("db", "url"),
    "IMAGE_ROOT": ("paths", "image_root"),
    "LOG_LEVEL": ("logging", "level"),
}


class ConfigError(Exception):
    """설정 오류. 메시지에 키 경로(예: `http.bogus_key`)가 들어 있다."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HttpConfig(_Section):
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)


class MqttConfig(_Section):
    url: str
    client_id: str = Field(min_length=1)
    topic_prefix: str = Field(min_length=1)
    keepalive_s: int = Field(ge=1)
    reconnect_min_s: int = Field(ge=1)
    reconnect_max_s: int = Field(ge=1)
    max_queued: int = Field(ge=0)

    @field_validator("url")
    @classmethod
    def _mqtt_url(cls, v: str) -> str:
        # mqtt://host[:port]만 받는다 (02-mqtt.md 1절)
        try:
            u = urlsplit(v)
            port = u.port
        except ValueError as e:
            raise ValueError(f"invalid mqtt url: {e}") from None
        if u.scheme != "mqtt" or not u.hostname or u.path not in ("", "/") or u.query or u.fragment:
            raise ValueError("must be mqtt://host[:port]")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("port out of range")
        return v

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""

    @property
    def port(self) -> int:
        return urlsplit(self.url).port or 1883

    @field_validator("reconnect_max_s")
    @classmethod
    def _reconnect_order(cls, v: int, info: ValidationInfo) -> int:
        lo = info.data.get("reconnect_min_s")
        if lo is not None and v < lo:
            raise ValueError(f"must be >= reconnect_min_s ({lo})")
        return v


class DbConfig(_Section):
    url: str
    batch_period_s: float = Field(gt=0)
    reconnect_interval_s: float = Field(gt=0)
    summary_period_s: float = Field(ge=0.5, le=2.5)

    @field_validator("url")
    @classmethod
    def _db_url(cls, v: str) -> str:
        # libpq URL: postgresql://user:password@host:port/dbname (07-runtime.md 1절)
        try:
            u = urlsplit(v)
            u.port  # noqa: B018 - 포트 형식 검사
        except ValueError as e:
            raise ValueError(f"invalid db url: {e}") from None
        if u.scheme not in ("postgresql", "postgres") or not u.hostname:
            raise ValueError("must be postgresql://user:password@host:port/dbname")
        return v


class PathsConfig(_Section):
    image_root: str = Field(min_length=1)

    @property
    def image_root_path(self) -> Path:
        """상대 경로는 저장소 루트 기준이다 (07-runtime.md 1절)."""
        p = Path(self.image_root)
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()


class LoggingConfig(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    @field_validator("level", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> Any:
        return v.upper() if isinstance(v, str) else v


class LineConfig(_Section):
    sensor_id: str = Field(min_length=1)


class InterlockConfig(_Section):
    pending_timeout_s: float = Field(ge=0.5, le=60)


class JoinConfig(_Section):
    max_gap_s: float = Field(gt=0)


class CorrelationConfig(_Section):
    period_s: float = Field(gt=0)
    lag_min_s: float = Field(ge=0)
    lag_max_s: float = Field(ge=0)
    lag_step_s: float = Field(gt=0)
    default_lag_s: float
    min_samples: int = Field(ge=3)
    bin_s: float = Field(gt=0)
    window_s: float | None = Field(default=None, gt=0)

    @field_validator("lag_max_s")
    @classmethod
    def _lag_order(cls, v: float, info: ValidationInfo) -> float:
        lo = info.data.get("lag_min_s")
        if lo is not None and v < lo:
            raise ValueError(f"must be >= lag_min_s ({lo:g})")
        return v

    @field_validator("default_lag_s")
    @classmethod
    def _default_lag_in_range(cls, v: float, info: ValidationInfo) -> float:
        # lag_min_s~lag_max_s 안이어야 한다 (04-analysis.md 3절)
        lo, hi = info.data.get("lag_min_s"), info.data.get("lag_max_s")
        if lo is not None and hi is not None and not lo <= v <= hi:
            raise ValueError(f"must be within lag_min_s..lag_max_s ({lo:g}..{hi:g})")
        return v


class PdmConfig(_Section):
    history_s: float = Field(gt=0)
    stale_s: float = Field(gt=0)


class DashboardConfig(_Section):
    line_stale_s: float = Field(gt=0)
    spectrum_stale_s: float = Field(gt=0)
    vibration_stale_s: float = Field(gt=0)
    vibration_window_chunks: int = Field(ge=1)
    vibration_buckets: int = Field(ge=1)
    recent_inspections: int = Field(ge=1)
    recent_alarms: int = Field(ge=1)
    recent_controls: int = Field(ge=1)


class Config(_Section):
    http: HttpConfig
    mqtt: MqttConfig
    db: DbConfig
    paths: PathsConfig
    logging: LoggingConfig
    line: LineConfig
    interlock: InterlockConfig
    join: JoinConfig
    correlation: CorrelationConfig
    pdm: PdmConfig
    dashboard: DashboardConfig


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """overlay를 base 위에 깊게 병합한다. 둘 다 dict인 값만 재귀하고 나머지는 overlay가 이긴다."""
    out: dict[str, Any] = dict(base)
    for k, v in overlay.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_yaml(path: Path, what: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"{what} {path}: cannot read ({e.strerror or e})") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"{what} {path}: invalid YAML ({e})") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{what} {path}: top level must be a mapping")
    return data


def _format_validation_error(err: ValidationError) -> str:
    lines = []
    for e in err.errors():
        path = ".".join(str(p) for p in e["loc"]) or "<root>"
        lines.append(f"{path}: {e['msg']}")
    return "invalid configuration:\n  " + "\n  ".join(lines)


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """설정을 읽어 검증한다. 오류면 `ConfigError`."""
    env = os.environ if env is None else env
    default_path = Path(env.get("FOPS_DEFAULT_CONFIG") or DEFAULT_CONFIG_PATH)
    data = _read_yaml(default_path, "default config")
    overlay_path = env.get("FOPS_CONFIG")
    if overlay_path:
        data = deep_merge(data, _read_yaml(Path(overlay_path), "overlay config"))
    for var, (section, key) in ENV_KEYS.items():
        if var in env:
            sec = data.get(section)
            data[section] = dict(sec) if isinstance(sec, Mapping) else {}
            data[section][key] = env[var]
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(_format_validation_error(e)) from None


def load_or_exit(env: Mapping[str, str] | None = None) -> Config:
    """`load_config`와 같지만 오류면 stderr에 쓰고 종료 코드 2로 끝낸다."""
    try:
        return load_config(env)
    except ConfigError as e:
        print(f"factory-operations: {e}", file=sys.stderr, flush=True)
        raise SystemExit(EXIT_CONFIG_ERROR) from None
