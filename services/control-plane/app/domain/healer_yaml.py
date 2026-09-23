"""Parser for the versioned healer.yaml application descriptor.

See app/schemas/healer_yaml.py for the schema and docs/healer-yaml.md for
the format itself.
"""

import yaml
from pydantic import ValidationError

from app.schemas.healer_yaml import HEALER_YAML_VERSION, HealerYamlV1


class HealerYamlParseError(Exception):
    """Raised for any parse/validation failure. `errors` is a list of
    {"field": "dotted.path", "message": "..."} — never a raw traceback,
    since this is meant to be shown directly to an administrator.
    """

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__("failed to parse healer.yaml: " + "; ".join(e["message"] for e in errors))


def parse_healer_yaml(raw_text: str) -> HealerYamlV1:
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise HealerYamlParseError(
            [{"field": "<yaml>", "message": f"invalid YAML: {exc}"}]
        ) from exc

    if not isinstance(data, dict):
        raise HealerYamlParseError(
            [
                {
                    "field": "<root>",
                    "message": "healer.yaml must be a mapping (YAML object) at the top level",
                }
            ]
        )

    version = data.get("version")
    if version != HEALER_YAML_VERSION:
        raise HealerYamlParseError(
            [
                {
                    "field": "version",
                    "message": (
                        f"unsupported healer.yaml version {version!r} — "
                        f"only {HEALER_YAML_VERSION} is supported"
                    ),
                }
            ]
        )

    try:
        return HealerYamlV1.model_validate(data)
    except ValidationError as exc:
        errors = [
            {
                "field": ".".join(str(part) for part in error["loc"]) or "<root>",
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        raise HealerYamlParseError(errors) from exc
