"""A failed external extraction must have safe, actionable diagnostics."""
import json
from pathlib import Path
import unittest
from urllib.error import HTTPError

from ml.document_agent.field_extractor import extract_verified_fields, evaluate_cases
from ml.document_agent.schema import UploadedDocument

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / 'examples' / 'realistic' / 'cases.json'


class FailureProvider:
    def __init__(self, error):
        self.error = error

    def extract_fields(self, document):
        raise self.error


class TestExtractionDiagnostics(unittest.TestCase):
    def setUp(self):
        self.document = UploadedDocument('doc-1', 'demo.txt', 'ИНН 7701234567\nВыручка 10 рублей')

    def test_http_status_but_no_response_body_or_credentials(self):
        exc = HTTPError('https://api.z.ai/api/paas/v4/chat/completions', 400,
                        'secret material', {'Authorization': 'Bearer secret'}, None)
        result = extract_verified_fields(self.document, FailureProvider(exc))
        self.assertEqual(result['diagnostic'], {'failure_kind': 'http_error', 'http_status': 400})
        self.assertEqual(result['issues'], ['model_extraction_failed'])
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('Bearer', json.dumps(result))

    def test_schema_error_has_allowlisted_reason(self):
        result = extract_verified_fields(self.document, FailureProvider(
            ValueError('annual_revenue_rub: expected integer ruble amount [PRIVATE DATA]')))
        self.assertEqual(result['diagnostic'], {
            'failure_kind': 'invalid_model_schema', 'failure_reason': 'incorrect_amount_type'})
        self.assertNotIn('PRIVATE DATA', json.dumps(result))

    def test_invalid_json_is_distinguished(self):
        result = extract_verified_fields(self.document, FailureProvider(
            json.JSONDecodeError('do not leak source text', 'sensitive model output', 0)))
        self.assertEqual(result['diagnostic']['failure_kind'], 'invalid_json')
        self.assertNotIn('sensitive', json.dumps(result))

    def test_single_case_mock_and_metrics(self):
        report = evaluate_cases(CASES, provider_name='mock', case_id='fin25')
        self.assertEqual(report['cases'], 1)
        self.assertEqual(report['successful_extractions'], 1)
        self.assertEqual(report['failed_extractions'], 0)
        self.assertEqual(report['non_null_field_accuracy'], 1.0)
        self.assertEqual(report['field_accuracy'], 1.0)

    def test_unknown_case_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, 'existing case'):
            evaluate_cases(CASES, provider_name='mock', case_id='nope')


if __name__ == '__main__':
    unittest.main()
