from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ActionCatalog:
    entries: tuple[tuple[str, str], ...]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(code for code, _ in self.entries)

    def require_code(self, code: object) -> str:
        if not isinstance(code, str) or code not in self.codes:
            raise ValueError(f'unknown action: {code!r}')
        return code


def validate_catalog(values: Mapping[str, str]) -> ActionCatalog:
    if not isinstance(values, Mapping) or not 2 <= len(values) <= 3:
        raise ValueError('catalog must contain two or three actions')
    entries = []
    for code, label in values.items():
        if not isinstance(code, str) or not code or code != code.strip():
            raise ValueError('action code must be a nonempty trimmed string')
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f'missing display name for action {code!r}')
        entries.append((code, label))
    return ActionCatalog(tuple(sorted(entries)))
