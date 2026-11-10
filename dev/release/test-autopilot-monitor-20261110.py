#!/usr/bin/env python3
"""Offline tests for durable alert identity, replay suppression and recovery."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

source=Path(__file__).with_name("autopilot-monitor-20261110.py")
spec=importlib.util.spec_from_file_location("autopilot_monitor",source)
monitor=importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)

class MonitorContractTests(unittest.TestCase):
    def test_healthy_empty_report(self):
        result=monitor.analyze_report(
            "===== READ-ONLY SNAPSHOT COMPLETE =====\nSUMMARY: PASS\n"
            "davarna-backend critical_log_matches=0\n",0)
        self.assertEqual(result,{})
    def test_duplicate_round_warning_identity_stable(self):
        a=monitor.analyze_report("ALERT DUPLICATE_LANE: LOW games=[51,52]\n===== READ-ONLY SNAPSHOT COMPLETE =====",0)
        b=monitor.analyze_report("ALERT DUPLICATE_LANE: LOW games=[51,52]\n===== READ-ONLY SNAPSHOT COMPLETE =====",0)
        self.assertEqual(set(a),set(b))
    def test_two_duplicate_lanes_not_merged(self):
        report=("ALERT DUPLICATE_LANE: LOW games=[91,94]\\n"
                "ALERT DUPLICATE_LANE: MEDIUM games=[92,95]\\n"
                "===== READ-ONLY SNAPSHOT COMPLETE =====")
        findings=monitor.analyze_report(report,0)
        self.assertIn("DUPLICATE_LANE:LOW",findings)
        self.assertIn("DUPLICATE_LANE:MEDIUM",findings)
        self.assertEqual(len(findings),2)
    def test_overdue_number_identity_ignores_seconds(self):
        a=monitor.analyze_report("ALERT OVERDUE_NUMBER: game=93 due_by=140s interval=15s\n===== READ-ONLY SNAPSHOT COMPLETE =====",0)
        b=monitor.analyze_report("ALERT OVERDUE_NUMBER: game=93 due_by=440s interval=15s\n===== READ-ONLY SNAPSHOT COMPLETE =====",0)
        self.assertEqual(set(a),set(b))
        self.assertIn("OVERDUE_NUMBER:93",a)
    def test_report_failed(self):
        report=monitor.analyze_report("BLOCKER: container missing",2)
        self.assertIn("MONITOR_COLLECTION_FAILED:GLOBAL",report)
    def test_first_alert_and_suppression(self):
        state,events=monitor.transition({"open":{}},{"OVERDUE_NUMBER:93":"warning"},100000)
        self.assertEqual(len(events),1)
        state["open"]["OVERDUE_NUMBER:93"]["last_sent"]=100000
        state,new=monitor.transition(state,{"OVERDUE_NUMBER:93":"warning age increased"},100300)
        self.assertEqual(new,[])
        _,new=monitor.transition(state,{"OVERDUE_NUMBER:93":"warning"},100000+monitor.RENOTIFY_SECONDS+1)
        self.assertEqual(len(new),1)
    def test_recovery_notifies_only_after_sent_alert(self):
        state,events=monitor.transition({"open":{}},{"STALLED_DRAW:93":"problem"},1000)
        state,events=monitor.transition(state,{},1300)
        self.assertEqual(events,[])
        state,events=monitor.transition({"open":{"STALLED_DRAW:93":{
            "first_seen":1000,"last_sent":1200,"message":"problem"}}},{},1300)
        self.assertEqual(events,[("RESOLVED","STALLED_DRAW:93","problem")])
        state,events=monitor.transition(state,{},1400)
        self.assertEqual(events,[("RESOLVED","STALLED_DRAW:93","problem")])
    def test_unexpected_worker_log_count_alert(self):
        r=monitor.analyze_report("davarna-backend critical_log_matches=3\n===== READ-ONLY SNAPSHOT COMPLETE =====",0)
        self.assertIn("RECENT_WORKER_LOG_ERRORS:davarna-backend",r)
    def test_missing_next_round_alert(self):
        r=monitor.analyze_report("ALERT MISSING_NEXT_ROUND: level=HIGH last_ended_id=93 elapsed_s=8888 configured_delay_s=600\n===== READ-ONLY SNAPSHOT COMPLETE =====",0)
        self.assertIn("MISSING_NEXT_ROUND:HIGH",r)
if __name__=="__main__":
    unittest.main()
