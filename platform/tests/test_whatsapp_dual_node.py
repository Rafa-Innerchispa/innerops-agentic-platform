import unittest

from raphiia_openai.notifications.evolution_client import resolve_inbound_node


class TestWhatsappDualNode(unittest.TestCase):
    def test_innerchispa_routes_amd(self):
        payload = {"instance": "Innerchispa", "event": "messages.upsert"}
        self.assertEqual(resolve_inbound_node(payload), "amd")

    def test_pcdoctor_routes_primary(self):
        payload = {"instance": "RalphiIA-pcdoctor"}
        self.assertEqual(resolve_inbound_node(payload), "primary")

    def test_amd_backup_alias(self):
        payload = {"instance": "RalfIA-amd-backup"}
        self.assertEqual(resolve_inbound_node(payload), "amd")

    def test_server_url_amd(self):
        payload = {"instance": "x", "server_url": "http://192.168.1.5:8082"}
        self.assertEqual(resolve_inbound_node(payload), "amd")


if __name__ == "__main__":
    unittest.main()
