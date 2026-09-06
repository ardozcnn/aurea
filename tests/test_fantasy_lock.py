import threading
import time
import unittest

from app import fantasy_bridge as fb


class FantasyLockTests(unittest.TestCase):
    def tearDown(self):
        fb._THREAD = None
        fb._SESSION = None

    def test_status_is_reentrant(self):
        with fb._LOCK:
            snap = fb.status()
        self.assertIn("phase", snap)

    def test_start_while_running_does_not_deadlock(self):
        stop = threading.Event()

        def hang():
            stop.wait(2)

        worker = threading.Thread(target=hang, daemon=True)
        worker.start()
        fb._THREAD = worker
        fb._SESSION = {"ok": True, "name": "Test"}
        started = time.time()
        snap = fb.start()
        elapsed = time.time() - started
        stop.set()
        worker.join(2)
        self.assertLess(elapsed, 1.0)
        self.assertTrue(snap.get("running"))
        self.assertIs(fb._THREAD, worker)


if __name__ == "__main__":
    unittest.main()
