import unittest
from unittest.mock import patch
from raphiia_openai import whatsapp_agent_router as router
class TestWhatsappAgentRouter(unittest.TestCase):
    def test_codex_uses_runner(self):
        with patch.object(router.codex_whatsapp_jobs,'request_job',return_value={'ok':True,'job_id':'cj_fixture'}) as call:
            trace={'message_id':'wa-msg-1','correlation_id':'wa-cid-1','conversation_ref':'whatsapp:fixture'}
            result=router.route_request('codex[quoteops]: revisa pruebas','593fixture',node='amd',trace=trace)
        self.assertEqual(result['route'],'codex_runner')
        call.assert_called_once_with('593fixture','revisa pruebas',target='quoteops',node='amd',trace=trace)
    def test_cursor_creates_canonical_mcp_task(self):
        with patch.object(router.coordination_live,'create_ops_task',return_value={'ok':True,'task_id':'ops_fixture','correlation_id':'cid'}) as call:
            trace={'message_id':'wa-msg-2','correlation_id':'wa-cid-2','conversation_ref':'whatsapp:fixture','related_project':'raphiia-openai'}
            result=router.route_request('cursor: revisa memoria','593fixture',trace=trace)
        self.assertEqual(result['route'],'coordination_mcp')
        self.assertEqual(result['task_id'],'ops_fixture')
        self.assertEqual(call.call_args.kwargs['assignee'],'cursor')
        self.assertEqual(call.call_args.kwargs['correlation_id'],'wa-cid-2')
        self.assertEqual(call.call_args.kwargs['source_message_id'],'wa-msg-2')
        self.assertEqual(call.call_args.kwargs['conversation_ref'],'whatsapp:fixture')
    def test_unknown_prefix_ignored(self):
        self.assertIsNone(router.route_request('shell: rm todo','593fixture'))
    def test_natural_codex_request_infers_quoteops(self):
        parsed = router.parse_request(
            'RalfIA, pídele a Codex que revise las pruebas del proyecto de cotizaciones'
        )
        self.assertEqual(
            parsed,
            ('codex', 'quoteops', 'revise las pruebas del proyecto de cotizaciones'),
        )
    def test_natural_antigravity_request(self):
        parsed = router.parse_request('Necesito que Antigravity revise la documentación del MCP')
        self.assertEqual(parsed, ('antigravity', None, 'revise la documentación del MCP'))
    def test_agent_discussion_is_not_a_job(self):
        self.assertIsNone(router.parse_request('¿Qué diferencia existe entre Codex y Cursor?'))
    def test_natural_shell_request_is_not_allowlisted(self):
        self.assertIsNone(router.parse_request('RalfIA, pídele a shell que borre todo'))
if __name__=='__main__': unittest.main()
