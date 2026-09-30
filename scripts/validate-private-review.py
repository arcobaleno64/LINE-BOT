"""Validate an approved I06 V3 projection without sending or printing its content."""

import argparse
import hashlib
import json
from pathlib import Path


class ValidationError(Exception):
    pass


def _read_json(path):
    try:
        raw = path.read_bytes()
        return raw, json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError('invalid_input') from exc


def _require(condition, reason):
    if not condition:
        raise ValidationError(reason)


def _has_forbidden_key(value):
    forbidden = {'expected_answer', 'expected_response', 'future_events', 'later_revision_outcomes'}
    if isinstance(value, dict):
        return any(key in forbidden or _has_forbidden_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_has_forbidden_key(item) for item in value)
    return False


def validate(manifest_path, bundle_path):
    """Check the pinned projection contract; this cannot prove non-reidentifiability."""
    _, manifest = _read_json(Path(manifest_path))
    bundle_raw, bundle = _read_json(Path(bundle_path))
    try:
        privacy = manifest['privacy']
        contract = manifest['replay_preparation']['revision_v3']
        _require(manifest['case_id'] == 'I06', 'wrong_case')
        _require(privacy['export_approved'] is True, 'not_approved')
        _require(privacy['export_scope'].startswith('deidentified projected messages only'), 'wrong_export_scope')
        _require(Path(bundle_path).name == contract['bundle_file'], 'wrong_bundle_file')
        digest = hashlib.sha256(bundle_raw).hexdigest()
        _require(digest == contract['bundle_sha256'], 'bundle_hash_mismatch')
        _require(bundle['schema_version'] == '0.3' and bundle['model_calls'] == 0,
                 'wrong_bundle_contract')
        _require(bundle['provider'] == 'Gemini' and bundle['model'] == 'gemini-3.8-flash',
                 'wrong_provider')
        requests = bundle['requests']
        _require(len(requests) == 4, 'wrong_request_count')
        expected = [('first-review', 'neutral'), ('first-review', 'evidence'),
                    ('revision-review', 'neutral'), ('revision-review', 'evidence')]
        _require([(item['checkpoint'], item['arm']) for item in requests] == expected,
                 'wrong_request_order')
        for item in requests:
            _require(item['response_contract'] == '0.3', 'wrong_response_contract')
            messages = item['messages']
            _require(len(messages) == 2 and [m['role'] for m in messages] == ['system', 'user'],
                     'wrong_message_roles')
            wire = json.dumps(messages, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            _require(hashlib.sha256(wire).hexdigest() == item['messages_sha256'],
                     'messages_hash_mismatch')
            source = json.loads(messages[1]['content'])
            _require(set(source) == {'task', 'visible_events', 'document', 'person_rules'},
                     'unexpected_payload_field')
            _require(set(source['document']) == {'blocks', 'limitations', 'redaction'},
                     'unexpected_document_field')
            _require(not _has_forbidden_key(source), 'future_answer_leak')
        return {'status': 'approved_projection_integrity_checked', 'request_count': 4,
                'bundle_sha256': digest}
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise ValidationError('invalid_contract') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.manifest, args.bundle)
    except ValidationError as exc:
        result = {'status': 'rejected', 'reason': str(exc)}
        print(json.dumps(result, separators=(',', ':')))
        return 1
    print(json.dumps(result, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
