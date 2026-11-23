import hashlib
import hmac
import json
from dataclasses import dataclass


_VERSION = 1
SUPPORTED_VERSIONS = (1, 2)
_FIELDS = {'version', 'machine_model', 'model_id', 'revision_id', 'body', 'fingerprint'}


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(',', ':'))


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for field, value in pairs:
        if field in result:
            raise ValueError(f'duplicate JSON field: {field!r}')
        result[field] = value
    return result


def read_json_object(encoded: str, fields: set[str]) -> dict:
    if not isinstance(encoded, str):
        raise ValueError('expected JSON text')
    try:
        result = json.loads(encoded, object_pairs_hook=_unique_fields)
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid JSON object') from error
    if not isinstance(result, dict) or set(result) != fields:
        raise ValueError('unexpected or missing fields')
    return result


@dataclass(frozen=True)
class EvidenceEnvelope:
    version: int
    machine_model: str
    model_id: int
    revision_id: int
    body: str
    fingerprint: str

    def identity_payload(self) -> dict:
        return {
            'version': self.version,
            'machine_model': self.machine_model,
            'model_id': self.model_id,
            'revision_id': self.revision_id,
            'body': self.body,
        }

    def to_json(self) -> str:
        return canonical_json({**self.identity_payload(), 'fingerprint': self.fingerprint})

    @classmethod
    def from_json(cls, encoded: str) -> 'EvidenceEnvelope':
        return cls(**read_json_object(encoded, _FIELDS))


def _validate_identity(envelope: EvidenceEnvelope) -> None:
    if type(envelope.version) is not int or envelope.version not in SUPPORTED_VERSIONS:
        raise ValueError('unsupported evidence version')
    model = envelope.machine_model
    if not isinstance(model, str) or not model or model != model.strip():
        raise ValueError('invalid evidence machine model')
    for identifier in (envelope.model_id, envelope.revision_id):
        if type(identifier) is not int or not 1 <= identifier < 2**63:
            raise ValueError('invalid evidence source ID')
    if not isinstance(envelope.body, str):
        raise ValueError('invalid evidence body encoding')


def _fingerprint(envelope: EvidenceEnvelope) -> str:
    return hashlib.sha256(canonical_json(envelope.identity_payload()).encode('ascii')).hexdigest()


def seal_envelope(
    machine_model: str, model_id: int, revision_id: int, body: str, version: int = _VERSION,
) -> EvidenceEnvelope:
    content = EvidenceEnvelope(version, machine_model, model_id, revision_id, body, '')
    _validate_identity(content)
    return EvidenceEnvelope(**content.identity_payload(), fingerprint=_fingerprint(content))


def verify_envelope(envelope: EvidenceEnvelope) -> None:
    if not isinstance(envelope, EvidenceEnvelope):
        raise ValueError('expected an evidence envelope')
    _validate_identity(envelope)
    fingerprint = envelope.fingerprint
    if (not isinstance(fingerprint, str) or len(fingerprint) != 64 or not fingerprint.isascii()
            or not hmac.compare_digest(_fingerprint(envelope), fingerprint)):
        raise ValueError('evidence fingerprint does not match its source and body')
