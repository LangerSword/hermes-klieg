"""Core test suite. stdlib unittest, no plugin host, no GPU, no Blender required.

    python3 -m unittest discover -s tests -v

These are the guarantees Klieg's README claims, so they are the ones tested:
a job is only done when its artefact is newer than the job; a stale artefact is
caught; a failing job keeps its exit code; the GPU lock excludes; bad input
returns an error instead of a traceback.
"""

import json
import os
import sys
import time
import tempfile
import unittest

# Hermetic: every test run gets its own plugin data dir, so job history from a
# previous run (or from the user's real ~/.hermes) cannot change an assertion.
os.environ["HERMES_PLUGIN_DATA"] = tempfile.mkdtemp(prefix="klieg-tests-")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import klieg_core as core
import klieg_tools as tools
import klieg_adapters as A


class JobLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="klieg-test-")

    def _art(self, name="a.png", age=0):
        p = os.path.join(self.tmp, name)
        with open(p, "w") as f:
            f.write("x")
        t = time.time() - age
        os.utime(p, (t, t))
        return p

    def test_detached_job_completes_and_verifies(self):
        art = os.path.join(self.tmp, "done.png")
        j = core.launch("t1", ["/bin/sh", "-c", f"sleep 0.4; echo x > {art}"], guard=[art])
        time.sleep(2)
        st = core.poll(j["job"])
        self.assertEqual(st["state"], "done")
        self.assertEqual(st["exit"], 0)
        v = core.verify(j["job"])
        self.assertTrue(v["ok"], v)
        self.assertEqual(len(v["artefacts"]), 1)

    def test_stale_artefact_is_not_success(self):
        old = self._art("stale.png", age=3600)
        j = core.launch("t2", ["/bin/sh", "-c", "true"], guard=[old])
        time.sleep(1.2)
        v = core.verify(j["job"])
        self.assertFalse(v["ok"])
        self.assertEqual(len(v["stale"]), 1)
        self.assertEqual(len(v["artefacts"]), 0)

    def test_missing_artefact_is_not_success(self):
        j = core.launch("t3", ["/bin/sh", "-c", "true"],
                        guard=[os.path.join(self.tmp, "nope.png")])
        time.sleep(1.2)
        v = core.verify(j["job"])
        self.assertFalse(v["ok"])
        self.assertEqual(len(v["missing"]), 1)

    def test_failure_keeps_exit_code(self):
        j = core.launch("t4", ["/bin/sh", "-c", "exit 42"])
        time.sleep(1.2)
        st = core.poll(j["job"])
        self.assertEqual(st["state"], "failed")
        self.assertEqual(st["exit"], 42)

    def test_kill_marks_job_and_releases_lock(self):
        j = core.launch("t5", ["/bin/sh", "-c", "sleep 30"], dcc="testgpu")
        time.sleep(0.6)
        self.assertIsNotNone(core.gpu_busy("testgpu"))
        core.kill(j["job"])
        time.sleep(0.6)
        self.assertIsNone(core.gpu_busy("testgpu"))
        self.assertEqual(core.read_status(j["job"])["state"], "killed")

    def test_unknown_job_is_reported_not_raised(self):
        self.assertEqual(core.poll("does-not-exist")["state"], "unknown")
        self.assertIn("state", core.verify("does-not-exist"))

    def test_partial_output_does_not_verify(self):
        """A render that dies at frame 1 of 3 must not pass on the frame it wrote."""
        d = os.path.join(self.tmp, "frames")
        os.makedirs(d)
        first = os.path.join(d, "0000.png")
        j = core.launch("t6", ["/bin/sh", "-c", f"echo x > {first}"], guard=[first],
                        expect={"dir": d, "min": 3, "ext": ".png"})
        time.sleep(1.2)
        v = core.verify(j["job"])
        self.assertFalse(v["ok"])
        self.assertEqual(v.get("counted"), 1)
        self.assertEqual(v.get("shortfall"), 2)


class GpuLock(unittest.TestCase):
    def test_second_holder_refused(self):
        core._take_lock("locktest", "job-a", os.getpid())
        held = core.gpu_busy("locktest")
        self.assertTrue(held)
        self.assertEqual(held["job"], "job-a")
        core.release_lock("locktest", "job-b")      # wrong job cannot release
        self.assertIsNotNone(core.gpu_busy("locktest"))
        core.release_lock("locktest", "job-a")
        self.assertIsNone(core.gpu_busy("locktest"))

    def test_dead_holder_is_reaped(self):
        p = core._lock_path("reaptest")
        with open(p, "w") as f:
            json.dump({"pid": 999999, "job": "ghost", "dcc": "reaptest"}, f)
        self.assertIsNone(core.gpu_busy("reaptest"))
        self.assertFalse(os.path.exists(p))


class FramesParser(unittest.TestCase):
    def test_ranges_and_lists(self):
        self.assertEqual(tools._frames("0-3"), [0, 1, 2, 3])
        self.assertEqual(tools._frames("0,5,9"), [0, 5, 9])
        self.assertEqual(tools._frames("0-2,7"), [0, 1, 2, 7])
        self.assertEqual(tools._frames([4, 2]), [4, 2])

    def test_empty_and_whitespace(self):
        self.assertEqual(tools._frames(""), [])
        self.assertEqual(tools._frames(" 1 , 2 "), [1, 2])


class ToolSurface(unittest.TestCase):
    def test_every_declared_tool_has_schema_and_handler(self):
        for spec in tools.TOOL_SPECS:
            self.assertTrue(callable(spec["handler"]), spec["name"])
            self.assertEqual(spec["schema"]["type"], "object")
            self.assertTrue(spec["description"])

    def test_probe_returns_json_with_adapters(self):
        out = json.loads(tools.h_probe({}))
        self.assertIn("adapters", out)
        names = {a["dcc"] for a in out["adapters"]}
        self.assertEqual(names, set(A.ADAPTERS))

    def test_jobs_status_without_job_is_an_error(self):
        out = json.loads(tools.h_jobs({"action": "status"}))
        self.assertIn("error", out)

    def test_publish_rejects_missing_dir_without_crashing(self):
        out = json.loads(tools.h_publish({"frames_dir": "/nonexistent/xyz",
                                          "out": "/tmp/klieg_should_not_exist.mp4"}))
        self.assertIn("error", out)


class AdapterContract(unittest.TestCase):
    def test_unknown_dcc_raises_keyerror(self):
        with self.assertRaises(KeyError):
            A.get("maya")

    def test_blender_argv_shape(self):
        argv = A.Blender().run_argv("/tmp/s.py", blend="/tmp/a.blend", args=["x"])
        self.assertIn("-b", argv)
        self.assertIn("--factory-startup", argv)
        self.assertIn("/tmp/s.py", argv)
        self.assertEqual(argv[-2:], ["--", "x"])

    def test_ae_declares_unsupported_instead_of_lying(self):
        ad = A.get("ae")
        self.assertIsNone(ad.run_argv("/tmp/s.py"))

    def test_safe_env_has_no_user_paths(self):
        self.assertNotIn("/home", A.SAFE_ENV["PATH"])
        self.assertIn("/usr/bin", A.SAFE_ENV["PATH"])


class Security(unittest.TestCase):
    def test_agent_secrets_do_not_reach_children(self):
        os.environ["OPENAI_API_KEY"] = "sk-should-never-be-in-a-render-log"
        env, dropped = core.child_environment({"MY_API_TOKEN": "abc", "PATH": "/usr/bin:/bin"})
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertIn("MY_API_TOKEN", dropped)
        self.assertNotIn("MY_API_TOKEN", env)
        self.assertEqual(env["PATH"], "/usr/bin:/bin")

    def test_allowlist_keeps_what_a_dcc_needs(self):
        env, _ = core.child_environment()
        for k in ("PATH", "HOME"):
            self.assertIn(k, env)

    def test_publish_refuses_system_and_credential_paths(self):
        bad = ("/etc/klieg.mp4", "/usr/local/klieg.mp4",
               os.path.expanduser("~/.ssh/klieg.mp4"))
        for out_path in bad:
            res = json.loads(tools.h_publish({"frames_dir": "/tmp", "out": out_path}))
            self.assertIn("error", res, out_path)
            self.assertIn("refusing", res["error"])


class Plan(unittest.TestCase):
    def test_plan_reports_blockers_without_running(self):
        out = json.loads(tools.h_plan({"blend": "/nope.blend", "frames": "0-3",
                                       "outdir": "/tmp/klieg-plan-test"}))
        self.assertFalse(out["would_run"])
        self.assertTrue(any("blend" in b for b in out["blockers"]))
        self.assertIsNone(out["predicted_seconds"])

    def test_plan_resolves_expected_files(self):
        d = tempfile.mkdtemp(prefix="klieg-plan-")
        blend = os.path.join(d, "a.blend")
        open(blend, "w").close()
        out = json.loads(tools.h_plan({"blend": blend, "frames": "0-2,7",
                                       "outdir": os.path.join(d, "f")}))
        self.assertEqual(out["frame_count"], 4)
        self.assertTrue(out["expected_first"].endswith("0000.png"))
        self.assertTrue(out["expected_last"].endswith("0007.png"))
        self.assertIn("-b", out["argv"])

    def test_plan_rejects_unknown_dcc(self):
        out = json.loads(tools.h_plan({"dcc": "maya", "frames": "0-1"}))
        self.assertIn("error", out)


class Queue(unittest.TestCase):
    def test_render_queues_behind_holder_then_runs(self):
        core._take_lock("qgpu", "holder", os.getpid())
        r = core.launch("q", ["/bin/sh", "-c", "true"], dcc="qgpu", queue=True)
        self.assertEqual(r["state"], "queued")
        self.assertEqual(r["position"], 1)
        self.assertIsNotNone(core.gpu_busy("qgpu"))
        core.release_lock("qgpu", "holder")
        started = core.dispatch("qgpu")
        self.assertEqual(len(started), 1)
        time.sleep(1.4)
        self.assertEqual(core.poll(r["job"])["state"], "done")

    def test_queue_false_refuses_instead_of_stacking(self):
        """Two renders on one GPU is the thing the lock exists to prevent."""
        core._take_lock("qgpu2", "holder", os.getpid())
        r = core.launch("q2", ["/bin/sh", "-c", "true"], dcc="qgpu2", queue=False)
        self.assertEqual(r["state"], "refused")
        self.assertEqual(r["held_by"], "holder")
        self.assertIn("error", r)
        core.release_lock("qgpu2", "holder")


if __name__ == "__main__":
    unittest.main()
