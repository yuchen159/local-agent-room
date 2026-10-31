import unittest

import room_watchdog as w


class WatchdogTests(unittest.TestCase):
    def test_detects_queued_work_with_no_turn(self):
        self.assertTrue(w.stalled({"active": None, "pendingCount": 1, "waiting": 0}))

    def test_ignores_running_or_scheduled_turns(self):
        self.assertFalse(w.stalled({"active": "DeepSeek", "pendingCount": 1, "waiting": 0}))
        self.assertFalse(w.stalled({"active": None, "pendingCount": 1, "waiting": 15}))
        self.assertFalse(w.stalled({"active": None, "pendingCount": 0, "waiting": 0}))

    def test_waits_for_threshold_then_retries_after_cooldown(self):
        self.assertFalse(w.due(1, 100, None))
        self.assertTrue(w.due(2, 100, None))
        self.assertFalse(w.due(3, 100, 100))                 # just tried
        self.assertFalse(w.due(3, 399, 100))                 # still cooling
        self.assertTrue(w.due(3, 400, 100))                  # cooldown elapsed

    def test_attempt_reset_allows_immediate_action_after_recovery(self):
        self.assertTrue(w.due(2, 500, None))

    def test_only_calls_an_advertised_endpoint(self):
        self.assertTrue(w.supports_recover({"recoverSupported": True}))
        self.assertFalse(w.supports_recover({"recoverSupported": False}))
        self.assertFalse(w.supports_recover({}))


if __name__ == "__main__":
    unittest.main()
