"""Create a retained small engineering task with external, frozen acceptance."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

CHECK = '''import importlib.util,json,pathlib,sys,unittest
candidate=pathlib.Path(sys.argv[1])
spec=importlib.util.spec_from_file_location("candidate_job",candidate/"job.py")
try:
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
except Exception as exc:
 print(json.dumps({"accepted":False,"tests":0,"failures":[type(exc).__name__+": "+str(exc)]}));raise SystemExit(0)
class Acceptance(unittest.TestCase):
 def test_immediate_success(self):
  self.assertEqual(module.poll_job(lambda _: {"status":"succeeded","result":{"url":"fixture://asset.glb"}},"job"),{"url":"fixture://asset.glb"})
 def test_queue_running_success(self):
  statuses=iter([{"status":"queued"},{"status":"running"},{"status":"succeeded","result":42}]); calls=[]
  def fetch(ident): calls.append(ident);return next(statuses)
  self.assertEqual(module.poll_job(fetch,"job",max_attempts=3),42);self.assertEqual(calls,["job"]*3)
 def test_failed_job(self):
  with self.assertRaises(RuntimeError):module.poll_job(lambda _: {"status":"failed","error":"generation failed"},"job")
 def test_timeout_budget(self):
  calls=[]
  def fetch(ident):calls.append(ident);return {"status":"running"}
  with self.assertRaises(TimeoutError):module.poll_job(fetch,"job",max_attempts=2)
  self.assertEqual(len(calls),2)
 def test_transient_error_retries(self):
  calls=[]
  def fetch(ident):
   calls.append(ident)
   if len(calls)==1:raise OSError("temporary fixture transport error")
   return {"status":"succeeded","result":42}
  self.assertEqual(module.poll_job(fetch,"job",max_attempts=2),42)
 def test_invalid_attempt_limit(self):
  for value in (0,-1,True,1.5):
   with self.subTest(value=value):
    with self.assertRaises(ValueError):module.poll_job(lambda _: {"status":"succeeded","result":42},"job",max_attempts=value)
suite=unittest.defaultTestLoader.loadTestsFromTestCase(Acceptance)
result=unittest.TestResult();suite.run(result)
print(json.dumps({"accepted":result.wasSuccessful(),"tests":result.testsRun,"failures":[str(t)+": "+trace for t,trace in result.failures+result.errors]}))
'''

def main():
    directory = Path(sys.argv[1]).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    project = directory / "project"
    project.mkdir()
    (project / "README.md").write_text("Retained engineering fixture: a job polling module. No external service calls.\n")
    checker = directory / "trusted_polling_check.py"
    checker.write_text(CHECK)
    specification = {
        "schema_version":"sisyfus.techlead.v1", "source":str(project),
        "objective":"Implement job.py with poll_job(fetch, job_id, max_attempts=5). Handle queued/running/succeeded/failed states. Return the succeeded result, raise RuntimeError for failed jobs, TimeoutError at exhaustion, ValueError for invalid positive integer limits. Retry transient OSError within the attempt limit; propagate other fetch errors. Never print or log job payloads because they may contain sensitive data. Do not call external services or sleep. The independent six-test acceptance suite must pass, and the independent reviewer must verify the complete stated contract.",
        "constraints":["Only job.py is writable", "No payload logging", "No permanent deletions; /usr/bin/trash only", "Do not modify trusted acceptance or controller state"],
        "deliverables":["job.py", "independent test and review receipts", "integrated candidate"],
        "roles":{"lead":{"driver":"claude","model":"claude-opus-5-5"},
                 "worker":{"driver":"codex","model":"gpt-6.1-sol"},
                 "reviewer":{"driver":"claude","model":"claude-opus-5-5"}},
        "checks":{"polling":{"argv":[sys.executable,"-I","-S",str(checker),"{candidate}"],
                  "code_hashes":{str(checker):hashlib.sha256(checker.read_bytes()).hexdigest()},
                  "contract":{"kind":"rules","pass_if":{"all":[{"path":"accepted","op":"eq","value":True},{"path":"tests","op":"eq","value":6}]},
                              "fail_if":{"all":[{"path":"accepted","op":"eq","value":False}]}}}},
        "required_checks":["polling"], "integration_checks":["polling"],
        "validation_kind":"REAL_NATIVE_ENGINEERING_VALIDATION", "parallelism":2,"timeout":900,
        "rsi":{"enabled":True,"auto_promote":True},
        "max_calls":None,"max_iterations":None,"max_tokens":None,"max_cost_usd":None,"max_wall_minutes":None}
    (directory / "mission.json").write_text(json.dumps(specification,ensure_ascii=False,indent=2))
    print(json.dumps({"specification":str(directory / "mission.json"),"project":str(project),"checker":str(checker),"tests":6}))

if __name__ == "__main__": main()
