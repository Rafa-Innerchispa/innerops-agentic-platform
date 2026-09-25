import unittest
from inneros_core_runtime.dev_swarm_scheduler import (
    _fanout_parse_model_json,
    _extract_balanced_json_candidates,
    _normalize_fanout_payload,
)


class TestModelJsonRecovery(unittest.TestCase):
    def test_fenced_json_with_prose(self):
        raw = '''I have prepared the requested solution.

```json
{
  "summary": "Fix authentication token issue",
  "files": [
    {
      "path": "src/auth/service.py",
      "content": "def authenticate():\n    return True\n"
    }
  ]
}
```

Let me know if you need additional modifications.'''
        parsed = _fanout_parse_model_json(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["summary"], "Fix authentication token issue")
        self.assertEqual(len(parsed["files"]), 1)
        self.assertEqual(parsed["files"][0]["path"], "src/auth/service.py")

    def test_nested_braces_in_file_content(self):
        raw = r'''{
  "summary": "Implement nested dictionary parser",
  "files": [
    {
      "path": "src/parser.py",
      "content": "def parse_dict():\n    data = {'outer': {'inner': 42}}\n    return data\n"
    }
  ]
}'''
        parsed = _fanout_parse_model_json(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["summary"], "Implement nested dictionary parser")
        self.assertIn("{'outer': {'inner': 42}}", parsed["files"][0]["content"])

    def test_trailing_commas_in_json(self):
        raw = r'''{
  "summary": "Handle trailing commas cleanly",
  "files": [
    {
      "path": "src/config.json",
      "content": "{\"debug\": true}",
    },
  ],
}'''
        parsed = _fanout_parse_model_json(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["summary"], "Handle trailing commas cleanly")
        self.assertEqual(len(parsed["files"]), 1)

    def test_multiline_string_literals(self):
        raw = '''{
  "summary": "Multiline raw file content",
  "files": [
    {
      "path": "src/component.tsx",
      "content": "export function Component() {
  return <div>Hello World</div>;
}"
    }
  ]
}'''
        parsed = _fanout_parse_model_json(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["summary"], "Multiline raw file content")
        self.assertIn("<div>Hello World</div>", parsed["files"][0]["content"])

    def test_normalized_payload_aliases(self):
        raw = '''{
  "summary": "Normalized writes alias",
  "writes": [
    {
      "path": "src/main.py",
      "content": "print('ok')"
    }
  ]
}'''
        parsed = _fanout_parse_model_json(raw)
        self.assertIsNotNone(parsed)
        self.assertIn("files", parsed)
        self.assertEqual(parsed["files"][0]["path"], "src/main.py")

    def test_duplicate_json_objects_prefers_valid(self):
        raw = '''Here is status info: {"status": "ok"}
And here is the file payload:
{
  "summary": "Actual changes",
  "files": [
    {"path": "lib/utils.py", "content": "x = 1"}
  ]
}'''
        parsed = _fanout_parse_model_json(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["summary"], "Actual changes")
        self.assertEqual(len(parsed["files"]), 1)

    def test_malformed_unbalanced_json_returns_none(self):
        raw = '''This is just plain text without any valid JSON structure at all.'''
        parsed = _fanout_parse_model_json(raw)
        self.assertIsNone(parsed)


if __name__ == "__main__":
    unittest.main()
