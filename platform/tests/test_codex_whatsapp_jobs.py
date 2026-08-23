import unittest
from unittest.mock import patch
from raphiia_openai import codex_whatsapp_jobs as jobs
class Col:
    def __init__(self): self.docs=[]
    def insert_one(self,d): self.docs.append(d)
    def find_one(self,q): return next((d for d in self.docs if all(d.get(k)==v for k,v in q.items())),None)
    def update_one(self,q,u): self.find_one(q).update(u.get('$set',{}))
class DB:
    def __init__(self): self.c=Col()
    def __getitem__(self,n): return self.c
class TestCodexJobs(unittest.TestCase):
    def test_two_step_and_safe_validation(self):
        db=DB()
        with patch.object(jobs.mongo_store,'get_db',return_value=db):
            trace={'message_id':'wa-msg-fixture','correlation_id':'wa-cid-fixture','conversation_ref':'whatsapp:fixture'}
            self.assertEqual(jobs.request_job('593999000000','estado del repo',target='mcp',trace=trace)['status'],'pending_confirmation')
            job=db.c.docs[0]
            self.assertEqual(job['target'],'mcp')
            self.assertEqual(job['correlation_id'],'wa-cid-fixture')
            self.assertEqual(job['source_message_id'],'wa-msg-fixture')
            self.assertTrue(job['requires_deploy_approval'])
            self.assertEqual(job['model_requested'],'gpt-5.6-sol')
            self.assertEqual(jobs.confirm_job('593888000000',job['job_id'])['error'],'codex_job_not_found_or_sender_mismatch')
            self.assertEqual(jobs.confirm_job('593999000000',job['job_id'])['status'],'approved')
            self.assertEqual(jobs.request_job('593999000000','usa mi api_key secreta')['error'],'codex_prompt_must_not_contain_secrets')
            self.assertEqual(jobs.request_job('593999000000','revisa',target='produccion')['error'],'codex_target_not_allowed')
    def test_worktree_path_is_confined(self):
        self.assertEqual(jobs._safe_worktree('cj_fixture123').parent,jobs.WORKTREE_ROOT.resolve())
        with self.assertRaisesRegex(ValueError,'invalid_job_id'):
            jobs._safe_worktree('../escape')
    def test_runner_environment_excludes_application_secrets(self):
        with patch.dict(jobs.os.environ, {'MCP_API_KEY':'fixture-secret'}, clear=False):
            self.assertNotIn('MCP_API_KEY',jobs._safe_env())
    def test_codex_jsonl_metadata_is_extracted(self):
        events='{"type":"thread.started","thread_id":"019f-fixture"}\n{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}\n'
        thread_id,usage=jobs._codex_metadata(events)
        self.assertEqual(thread_id,'019f-fixture')
        self.assertEqual(usage,{'input_tokens':10,'output_tokens':2})
if __name__=='__main__': unittest.main()
