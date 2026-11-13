"""Run the real monitor shell script with all external commands replaced; no network."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class MonitorDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / ".env.prod").write_text("BACKUP_BOT_TOKEN=TEST_ONLY\nBACKUP_CHAT_ID=123\n")
        self.fixture = {"time": 10000, "disk": 30, "mem": 30, "swap": 95, "send_ok": True}
        executable = '''#!/usr/local/bin/python
import json,os,sys,pathlib
p=pathlib.Path(os.environ["FIXTURE_ROOT"])
f=json.loads((p/"fixture.json").read_text())
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
if name=="sudo":os.execvp(args[0],args)
elif name=="date":print(f["time"] if args==["+%s"] else "TEST-TIME-"+str(f["time"]))
elif name=="hostname":print("ISOLATED")
elif name=="df":print("Filesystem 1024-blocks Used Available Capacity Mounted on\\nmock 1000 300 700 "+str(f["disk"])+"% /")
elif name=="free":print("Mem: 100 0 0 0 0 "+str(100-f["mem"])+"\\nSwap: 100 "+str(f["swap"])+" 0")
elif name=="docker":print("healthy" if any("Health" in a for a in args) else "true")
elif name=="find":print("0 /test-backup.sql.gz")
elif name=="stat":print(f["time"]-100)
elif name=="curl":
 if "-X" in args:
  with (p/"sends.jsonl").open("a") as out:out.write(json.dumps(args)+"\\n")
  sys.exit(0 if f["send_ok"] else 22)
'''
        for name in ("sudo", "date", "hostname", "df", "free", "docker", "find", "stat", "curl"):
            target = self.bin / name
            target.write_text(executable)
            target.chmod(0o755)
        self.env = {**os.environ, "PATH": str(self.bin)+":"+os.environ["PATH"],
                    "APP_DIR": str(self.root), "LOG_DIR": str(self.root/"logs"),
                    "STATE_DIR": str(self.root/"state"), "FIXTURE_ROOT": str(self.root)}
        self.script = Path(__file__).resolve().parents[2] / "scripts/node2-monitor.sh"

    def scan(self, **changes):
        self.fixture.update(changes)
        (self.root/"fixture.json").write_text(json.dumps(self.fixture))
        subprocess.run(["bash", str(self.script)], env=self.env, check=True, capture_output=True)

    def sends(self):
        path = self.root/"sends.jsonl"
        return path.read_text().splitlines() if path.exists() else []

    def test_timestamp_and_percentage_changes_do_not_bypass_cooldown(self):
        self.scan()
        self.scan(time=10060, swap=97)
        self.assertEqual(len(self.sends()), 1)
        self.scan(time=13600)
        self.assertEqual(len(self.sends()), 2)

    def test_failed_delivery_retries_and_does_not_ack(self):
        self.scan(send_ok=False)
        self.assertFalse((self.root/"state/last_sent_at").exists())
        self.scan(time=10060, send_ok=True)
        self.assertEqual(len(self.sends()), 2)
        self.scan(time=10120)
        self.assertEqual(len(self.sends()), 2)

    def test_recovery_failure_retries_and_success_is_sent_once(self):
        self.scan()
        self.scan(time=10060, swap=10, send_ok=False)
        self.scan(time=10120, send_ok=True)
        self.scan(time=10180)
        self.assertEqual(len(self.sends()), 3)
        self.assertIn("recovered", self.sends()[-1])

    def test_new_issue_bypasses_cooldown_but_healthy_start_is_silent(self):
        self.scan(swap=10)
        self.assertEqual(len(self.sends()), 0)
        self.scan(time=10060, swap=95)
        self.scan(time=10120, disk=90)
        self.assertEqual(len(self.sends()), 2)

    def test_existing_monitor_ack_migrates_without_duplicate(self):
        directory = self.root/"state"
        directory.mkdir()
        (directory/"last_sent_at").write_text("9999")
        (directory/"previous_issues.txt").write_text("Davarna monitor ALERT on NODE2\nTime: old\n\nSwap usage >= 90%\n")
        self.scan()
        self.assertEqual(len(self.sends()), 0)


if __name__ == "__main__":
    unittest.main()
