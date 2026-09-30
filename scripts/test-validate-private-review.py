"""Offline tests for the private review projection boundary."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    'validator', Path(__file__).with_name('validate-private-review.py'))
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ProjectionValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.manifest_path = root / 'manifest.json'
        self.bundle_path = root / 'bundle.json'
        source = {'task': 'Review a document', 'visible_events': [],
                  'document': {'blocks': [], 'limitations': [], 'redaction': {}},
                  'person_rules': []}
        self.bundle = {'schema_version': '0.3', 'provider': 'Gemini',
                       'model': 'gemini-3.8-flash', 'model_calls': 0, 'requests': []}
        for checkpoint in ('first-review', 'revision-review'):
            for arm in ('neutral', 'evidence'):
                messages = [{'role': 'system', 'content': 'Use evidence only'},
                            {'role': 'user', 'content': json.dumps(source)}]
                digest = hashlib.sha256(json.dumps(messages, ensure_ascii=False,
                          separators=(',', ':')).encode('utf-8')).hexdigest()
                self.bundle['requests'].append({'checkpoint': checkpoint, 'arm': arm,
                                               'response_contract': '0.3',
                                               'messages_sha256': digest, 'messages': messages})
        self.manifest = {'case_id': 'I06',
                         'privacy': {'export_approved': True,
                                     'export_scope': 'deidentified projected messages only'},
                         'replay_preparation': {'revision_v3': {'bundle_file': 'bundle.json'}}}
        self.save()

    def save(self):
        raw = json.dumps(self.bundle, ensure_ascii=False).encode('utf-8')
        self.bundle_path.write_bytes(raw)
        self.manifest['replay_preparation']['revision_v3']['bundle_sha256'] = hashlib.sha256(raw).hexdigest()
        self.manifest_path.write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_reviewed_projection_passes_without_returning_content(self):
        result = validator.validate(self.manifest_path, self.bundle_path)
        self.assertEqual(result['status'], 'approved_projection_integrity_checked')
        self.assertEqual(result['request_count'], 4)
        self.assertNotIn('Review a document', str(result))

    def test_modified_bundle_is_rejected_before_payload_use(self):
        self.bundle_path.write_bytes(self.bundle_path.read_bytes() + b' ')
        with self.assertRaisesRegex(validator.ValidationError, 'bundle_hash_mismatch'):
            validator.validate(self.manifest_path, self.bundle_path)

    def test_missing_privacy_approval_is_rejected(self):
        self.manifest['privacy']['export_approved'] = False
        self.save()
        with self.assertRaisesRegex(validator.ValidationError, 'not_approved'):
            validator.validate(self.manifest_path, self.bundle_path)

    def test_future_answer_inside_payload_is_rejected_even_when_hashes_match(self):
        source = json.loads(self.bundle['requests'][0]['messages'][1]['content'])
        source['visible_events'] = [{'future_events': ['future reviewer decision']}]
        messages = copy.deepcopy(self.bundle['requests'][0]['messages'])
        messages[1]['content'] = json.dumps(source)
        self.bundle['requests'][0]['messages'] = messages
        self.bundle['requests'][0]['messages_sha256'] = hashlib.sha256(
            json.dumps(messages, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
        self.save()
        with self.assertRaisesRegex(validator.ValidationError, 'future_answer_leak'):
            validator.validate(self.manifest_path, self.bundle_path)


if __name__ == '__main__':
    unittest.main()
