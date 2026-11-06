import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from inneros_incident_room.switch_event import RoomPolicy, ConnectionState, SwitchConfig


def event(mid, content, sender="@human:localhost"):
    return {"event":"message", "id": int(mid), "data":{"room_id":"!room:localhost",
        "payload":{"addressed":True,"sender":sender,"message_id":mid,"body":content}}}


class JournalTests(unittest.TestCase):
    def test_pending_approval_survives_restart_but_cannot_reexecute(self):
        clock=lambda:100.0
        p=RoomPolicy("!room:localhost","@human:localhost",clock=clock,id_factory=lambda:"abc")
        p.handle(event("1","!incident"))
        action=p.pending["action"].action_id
        with TemporaryDirectory() as d:
            config=SwitchConfig("http://127.0.0.1:9999","agent","fake","!room:localhost","@human:localhost",Path(d)/"conn.json")
            state=ConnectionState(config)
            state.policy_snapshot=p.snapshot()
            state.persist()
            resumed=ConnectionState(config)
            fresh=RoomPolicy("!room:localhost","@human:localhost",clock=clock)
            fresh.restore(resumed.policy_snapshot)
            self.assertEqual(fresh.pending["action"].action_id,action)
            result=fresh.handle(event("2","!approve "+action))
            self.assertIn("verified_simulation",result)
            self.assertEqual(fresh.state["synthetic-camera-a"],"healthy")
            resumed.policy_snapshot=fresh.snapshot()
            resumed.pending_replies["2"]=result
            resumed.persist()
            fresh2=RoomPolicy("!room:localhost","@human:localhost",clock=clock)
            fresh2.restore(ConnectionState(config).policy_snapshot)
            self.assertIsNone(fresh2.handle(event("2","!approve "+action)))
            self.assertEqual(fresh2.state["synthetic-camera-a"],"healthy")

    def test_pending_reply_kept_in_journal(self):
        with TemporaryDirectory() as d:
            config=SwitchConfig("http://127.0.0.1:9999","agent","FAKE-NOT-SAVED","room","human",Path(d)/"conn.json")
            conn=ConnectionState(config)
            conn.pending_replies["m3"]="synthetic approved receipt"
            conn.persist()
            obj=json.loads(config.state_path.read_text())
            self.assertIn("m3",obj["pending_replies"])
            self.assertNotIn("FAKE-NOT-SAVED",config.state_path.read_text())
            self.assertEqual(ConnectionState(config).pending_replies["m3"],"synthetic approved receipt")

    def test_restore_filters_real_device_name(self):
        p=RoomPolicy("room","human")
        p.restore({"state":{"switch-prod":"healthy","synthetic-camera-a":"healthy"},"pending":None})
        self.assertEqual(p.state,{"synthetic-camera-a":"healthy"})


if __name__ == "__main__": unittest.main()