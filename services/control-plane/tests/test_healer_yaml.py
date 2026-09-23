import pytest

from app.domain.healer_yaml import HealerYamlParseError, parse_healer_yaml

WINDOWS_YAML = """
version: 1
name: rit-academic-erp
adapter: windows-waitress-service
source:
  type: folder
  location: C:\\apps\\erp
windows:
  python_executable: C:\\apps\\erp\\venv\\Scripts\\python.exe
  wsgi_module: erp.wsgi
  settings_module: erp.settings.production
health:
  path: /health/
ports:
  start: 9034
  end: 9039
domain:
  hostname: erp.ritrjpm.edu.in
  cert_path: /etc/healer/certs/ritrjpm.edu.in.crt
  key_path: /etc/healer/certs/ritrjpm.edu.in.key
secrets:
  - DB_PASSWORD
"""

LINUX_YAML = """
version: 1
name: internal-api
adapter: linux-docker
source:
  type: dockerfile
  location: ./Dockerfile
linux:
  internal_port: 8000
health:
  path: /healthz
ports:
  start: 9100
  end: 9104
"""


def test_parses_a_valid_windows_config():
    config = parse_healer_yaml(WINDOWS_YAML)
    assert config.name == "rit-academic-erp"
    assert config.adapter == "windows-waitress-service"
    assert config.windows.wsgi_module == "erp.wsgi"
    assert config.ports.start == 9034
    assert config.secrets == ["DB_PASSWORD"]


def test_parses_a_valid_linux_config():
    config = parse_healer_yaml(LINUX_YAML)
    assert config.adapter == "linux-docker"
    assert config.linux.internal_port == 8000
    assert config.source.type == "dockerfile"


def test_rejects_invalid_yaml_syntax():
    with pytest.raises(HealerYamlParseError) as exc_info:
        parse_healer_yaml("not: valid: yaml: [")
    assert exc_info.value.errors[0]["field"] == "<yaml>"


def test_rejects_non_mapping_top_level():
    with pytest.raises(HealerYamlParseError):
        parse_healer_yaml("- just\n- a\n- list\n")


def test_rejects_unsupported_version():
    with pytest.raises(HealerYamlParseError) as exc_info:
        parse_healer_yaml("version: 2\nname: x\n")
    assert "version" in exc_info.value.errors[0]["field"]


def test_windows_adapter_requires_windows_section():
    yaml_text = """
version: 1
name: x
adapter: windows-waitress-service
source:
  type: folder
  location: /tmp
health:
  path: /health
ports:
  start: 9000
  end: 9001
"""
    with pytest.raises(HealerYamlParseError) as exc_info:
        parse_healer_yaml(yaml_text)
    assert any("windows" in e["message"] for e in exc_info.value.errors)


def test_windows_adapter_rejects_docker_source_type():
    yaml_text = """
version: 1
name: x
adapter: windows-waitress-service
source:
  type: dockerfile
  location: /tmp
windows:
  python_executable: /usr/bin/python3
  wsgi_module: x.wsgi
  settings_module: x.settings
health:
  path: /health
ports:
  start: 9000
  end: 9001
"""
    with pytest.raises(HealerYamlParseError):
        parse_healer_yaml(yaml_text)


def test_health_path_must_be_absolute():
    yaml_text = LINUX_YAML.replace("path: /healthz", "path: healthz")
    with pytest.raises(HealerYamlParseError) as exc_info:
        parse_healer_yaml(yaml_text)
    assert any("health" in e["field"] for e in exc_info.value.errors)


def test_port_range_end_must_be_gte_start():
    yaml_text = LINUX_YAML.replace("start: 9100\n  end: 9104", "start: 9104\n  end: 9100")
    with pytest.raises(HealerYamlParseError):
        parse_healer_yaml(yaml_text)
