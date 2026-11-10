import unittest
from src.tools import create_agent_message, handle_task_claim

class TestTools(unittest.TestCase):
    def test_create_agent_message(self):
        task_id = '123'
        correlation_id = 'abc'
        message = create_agent_message(task_id, correlation_id)
        self.assertEqual(message, {'task_id': task_id, 'correlation_id': correlation_id})

    def test_handle_task_claim(self):
        task_id = '123'
        correlation_id = 'abc'
        result = handle_task_claim(task_id, correlation_id)
        self.assertIn('status', result)
        self.assertEqual(result['status'], 'leased')

if __name__ == '__main__':
    unittest.main()
