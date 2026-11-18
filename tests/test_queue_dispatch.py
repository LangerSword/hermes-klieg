"""The queue must work through the TOOL, not only through the engine.

Regression: h_render refused every busy-GPU render before core.launch could see
the queue flag, so the flagship "second render queues" behaviour was unreachable
from the tool surface. Also: dispatch must not strand a free host behind a busy
one, a terminal holder's lock must be reaped even if its pid was reused, and
kill must hand the GPU straight to the next queued job.
"""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-queue-"))

import klieg_core as core
import klieg_tools as tools


class FakeAdapter:
    name = "blender"

    def detect(self):
        return {"dcc": self.name, "found": True, "path": "/fake/blender", "version": "5.3.0"}

    def find_binary(self):
        return "/fake/blender"

    def run_argv(self, script, blend=None, args=None):
        return ["/bin/sh", "-c", "true"]

    def render_argv(self, frames, outdir, samples, pct, blend, tag=""):
        return ["/bin/sh", "-c", "true"]


def drain(job, timeout=5):
    """Poll a job to a terminal state so no child is left live at exit."""
    deadline = time.time() + timeout
    st = core.read_status(job)
    while time.time() < deadline and st.get("state") in ("running", "queued"):
        st = core.poll(job)
        if st.get("state") in ("running", "queued"):
            time.sleep(0.05)
    if st.get("state") in ("running", "queued"):
        st = core.kill(job)
    return st


class HandlerQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="klieg-q-")
        self.blend = os.path.join(self.tmp, "s.blend")
        with open(self.blend, "w") as f:
            f.write("x")
        self.dcc = "qgpu-handler"
        self.holder = core.launch("holder", ["/bin/sh", "-c", "sleep 30"],
                                  dcc=self.dcc, queue=False)
        self.addCleanup(lambda: drain(self.holder["job"]))

    def _render(self, queue):
        with mock.patch.object(tools.A, "get", return_value=FakeAdapter()):
            return __import__("json").loads(tools.h_render({
                "dcc": self.dcc, "blend": self.blend, "frames": "0-1",
                "outdir": os.path.join(self.tmp, "out"), "queue": queue}))

    def test_render_queues_behind_holder_through_the_tool(self):
        r = self._render(queue=True)
        self.assertEqual(r["state"], "queued", r)
        self.assertEqual(r["position"], 1)
        self.assertEqual(r["held_by"], self.holder["job"])
        self.addCleanup(lambda: drain(r["job"]))
        # Freeing the holder must start the queued render.
        core.kill(self.holder["job"])
        st = drain(r["job"])
        self.assertEqual(st["state"], "done", st)

    def test_render_queue_false_refuses_through_the_tool(self):
        r = self._render(queue=False)
        self.assertEqual(r["state"], "refused", r)
        self.assertIn("one GPU", r["error"])


class DispatchCrossHost(unittest.TestCase):
    def test_free_host_advances_behind_busy_one(self):
        busy, free = "qgpu-busy", "qgpu-free"
        # Both hosts busy -> both jobs queue. Then the free host's holder exits
        # naturally (watcher releases the lock; nothing dispatches until a poll,
        # list or explicit dispatch). The FIFO scan meets the busy host first.
        holderA = core.launch("holdA", ["/bin/sh", "-c", "sleep 30"], dcc=busy, queue=False)
        holderB = core.launch("holdB", ["/bin/sh", "-c", "sleep 0.5"], dcc=free, queue=False)
        ja = core.launch("a", ["/bin/sh", "-c", "true"], dcc=busy, queue=True)
        jb = core.launch("b", ["/bin/sh", "-c", "true"], dcc=free, queue=True)
        try:
            self.assertEqual(ja["state"], "queued")
            self.assertEqual(jb["state"], "queued")
            drain(holderB["job"])          # exits + releases lock, no dispatch
            self.assertIsNone(core.gpu_busy(free))
            real = os.listdir(core.jobs_dir())
            # dispatch only ever lists the jobs dir; force the busy host's job
            # to sort first in the FIFO scan.
            with mock.patch.object(core.os, "listdir", return_value=sorted(real)):
                started = core.dispatch()
            self.assertEqual([s["job"] for s in started], [jb["job"]],
                             "a busy host must not strand a free host's queued job")
            self.assertEqual(core.read_status(ja["job"])["state"], "queued")
        finally:
            core.kill(holderA["job"])
            drain(holderB["job"])
            drain(ja["job"])
            drain(jb["job"])


class StaleLock(unittest.TestCase):
    def test_terminal_holder_lock_is_reaped_even_with_live_pid(self):
        dcc = "qgpu-stale"
        job = "dead-holder"
        os.makedirs(os.path.join(core.jobs_dir(), job), exist_ok=True)
        core._write_status(job, job=job, state="done")
        # os.getpid() is alive: only the job-state check can reap this lock.
        core._take_lock(dcc, job, os.getpid())
        self.assertIsNone(core.gpu_busy(dcc), "terminal holder's lock wedged the host")
        self.assertFalse(os.path.exists(core._lock_path(dcc)))

    def test_kill_hands_gpu_to_next_queued_job(self):
        dcc = "qgpu-kill"
        holder = core.launch("hold", ["/bin/sh", "-c", "sleep 30"], dcc=dcc, queue=False)
        nxt = core.launch("next", ["/bin/sh", "-c", "true"], dcc=dcc, queue=True)
        self.assertEqual(nxt["state"], "queued")
        try:
            core.kill(holder["job"])
            st = drain(nxt["job"])
            self.assertEqual(st["state"], "done",
                             "kill must dispatch the queue, not wait for a poll")
        finally:
            drain(holder["job"])
            drain(nxt["job"])


if __name__ == "__main__":
    unittest.main()