"""설정 로딩 (docs/spec/01-core.md 4절, 08-verification.md 3.1절)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from factory_operations import config as cfgmod
from factory_operations.config import ConfigError, load_config, load_or_exit

REPO = Path(__file__).resolve().parents[2]


def write_yaml(tmp_path: Path, data, name: str = "overlay.yaml") -> str:
    p = tmp_path / name
    p.write_text(data if isinstance(data, str) else yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def expect_exit_2(env, capsys, key_path: str) -> str:
    with pytest.raises(SystemExit) as ei:
        load_or_exit(env)
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert key_path in err
    return err


def test_defaults_loaded():
    c = load_config({})
    default = yaml.safe_load((REPO / "config" / "default.yaml").read_text())
    assert c.http.host == "0.0.0.0"
    assert c.http.port == 8080
    assert c.mqtt.url == "mqtt://localhost:1883"
    assert (c.mqtt.host, c.mqtt.port) == ("localhost", 1883)
    assert c.mqtt.topic_prefix == "factory"
    assert c.db.url == "postgresql://factory:factory@localhost:5432/factory"
    assert c.logging.level == "INFO"
    assert c.interlock.pending_timeout_s == 5.0
    assert c.correlation.default_lag_s == 13
    assert c.correlation.window_s is None
    assert c.dashboard.vibration_buckets == 500
    # 모델 덤프가 기본 파일과 같다 (모든 키가 파일에서 왔다)
    dumped = c.model_dump()
    for section, values in default.items():
        for key, value in values.items():
            assert dumped[section][key] == value, (section, key)
    # 상대 경로는 저장소 루트 기준
    assert c.paths.image_root_path == (REPO / "data").resolve()


def test_overlay_deep_merge(tmp_path):
    f = write_yaml(tmp_path, {"mqtt": {"keepalive_s": 45}, "correlation": {"window_s": 600}})
    c = load_config({"FOPS_CONFIG": f})
    assert c.mqtt.keepalive_s == 45
    # 같은 절의 다른 키는 기본값이 남는다
    assert c.mqtt.client_id == "factory-operations"
    assert c.mqtt.url == "mqtt://localhost:1883"
    assert c.correlation.window_s == 600
    assert c.correlation.lag_max_s == 30
    assert c.http.port == 8080


def test_default_config_path_env(tmp_path):
    base = yaml.safe_load((REPO / "config" / "default.yaml").read_text())
    base["http"]["port"] = 9090
    f = write_yaml(tmp_path, base, "default.yaml")
    assert load_config({"FOPS_DEFAULT_CONFIG": f}).http.port == 9090


def test_env_overrides_file(tmp_path):
    f = write_yaml(tmp_path, {"http": {"port": 9000}, "mqtt": {"url": "mqtt://from-file:1884"}})
    env = {
        "FOPS_CONFIG": f,
        "HTTP_PORT": "18280",
        "HTTP_HOST": "127.0.0.1",
        "MQTT_URL": "mqtt://broker",
        "TOPIC_PREFIX": "plant",
        "DATABASE_URL": "postgresql://u:p@db:5433/x",
        "IMAGE_ROOT": "/data",
        "LOG_LEVEL": "debug",
    }
    c = load_config(env)
    assert c.http.port == 18280
    assert c.http.host == "127.0.0.1"
    assert (c.mqtt.host, c.mqtt.port) == ("broker", 1883)
    assert c.mqtt.topic_prefix == "plant"
    assert c.db.url == "postgresql://u:p@db:5433/x"
    assert c.paths.image_root_path == Path("/data")
    assert c.logging.level == "DEBUG"
    # 환경 변수가 없는 키는 overlay 값
    assert load_config({"FOPS_CONFIG": f}).http.port == 9000


def test_unknown_key_exits_2(tmp_path, capsys):
    f = write_yaml(tmp_path, "http:\n  bogus_key: 1\n")
    expect_exit_2({"FOPS_CONFIG": f}, capsys, "http.bogus_key")
    f2 = write_yaml(tmp_path, "nosuch_section:\n  a: 1\n", "o2.yaml")
    expect_exit_2({"FOPS_CONFIG": f2}, capsys, "nosuch_section")


def test_out_of_range_exits_2(tmp_path, capsys):
    f = write_yaml(tmp_path, {"interlock": {"pending_timeout_s": 0}})
    expect_exit_2({"FOPS_CONFIG": f}, capsys, "interlock.pending_timeout_s")
    f = write_yaml(tmp_path, {"correlation": {"default_lag_s": 40}})
    expect_exit_2({"FOPS_CONFIG": f}, capsys, "correlation.default_lag_s")
    f = write_yaml(tmp_path, {"db": {"summary_period_s": 3.0}})
    expect_exit_2({"FOPS_CONFIG": f}, capsys, "db.summary_period_s")
    expect_exit_2({"HTTP_PORT": "70000"}, capsys, "http.port")


def test_format_errors_exit_2(tmp_path, capsys):
    expect_exit_2({"HTTP_PORT": "abc"}, capsys, "http.port")
    expect_exit_2({"MQTT_URL": "tcp://broker:1883"}, capsys, "mqtt.url")
    expect_exit_2({"DATABASE_URL": "mysql://x"}, capsys, "db.url")
    expect_exit_2({"LOG_LEVEL": "LOUD"}, capsys, "logging.level")
    f = write_yaml(tmp_path, "http: [1, 2\n", "broken.yaml")
    with pytest.raises(ConfigError):
        load_config({"FOPS_CONFIG": f})
    with pytest.raises(ConfigError):
        load_config({"FOPS_CONFIG": str(tmp_path / "missing.yaml")})


def test_deep_merge_replaces_non_mapping():
    assert cfgmod.deep_merge({"a": {"b": 1, "c": 2}, "d": [1]}, {"a": {"b": 3}, "d": [2]}) == {
        "a": {"b": 3, "c": 2},
        "d": [2],
    }


def test_serve_exits_2_on_unknown_key(tmp_path):
    f = write_yaml(tmp_path, "http:\n  bogus_key: 1\n")
    r = subprocess.run(
        [sys.executable, "-m", "factory_operations", "serve"],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO / "src"), "FOPS_CONFIG": f},
    )
    assert r.returncode == 2
    assert "http.bogus_key" in r.stderr
