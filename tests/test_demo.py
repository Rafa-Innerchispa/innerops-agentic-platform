import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = (ROOT / 'src' / 'server.js').read_text(encoding='utf-8')
PACKAGE = (ROOT / 'package.json').read_text(encoding='utf-8')

class InnerOSDemoTests(unittest.TestCase):
    def test_required_modules_present(self):
        for label in ['Overview','Workforce','Payroll','Access','Visitors','Credentials','Devices','ARIA','Workflows','Approvals','Audit','Settings']:
            self.assertIn(label, SERVER)

    def test_existing_workforce_orgs_preserved_in_ui(self):
        for org in ['FEMAR','IA PRO','PC Doctor']:
            self.assertIn(org, SERVER)
        self.assertIn('Existing organization', SERVER)

    def test_health_and_cloud_port(self):
        self.assertIn("'/health'", SERVER)
        self.assertIn('process.env.PORT', SERVER)
        self.assertIn('0.0.0.0', SERVER)

    def test_node_start_script(self):
        self.assertIn('node src/server.js', PACKAGE)

if __name__ == '__main__':
    unittest.main()
