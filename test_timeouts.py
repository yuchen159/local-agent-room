import unittest
from agents import TurnClock, TURN_IDLE_SECONDS, TURN_MAX_SECONDS


class Timeouts(unittest.TestCase):
    def test_work_with_activity_continues_beyond_old_three_minute_limit(self):
        clock=TurnClock(0)
        clock.touch(170)
        clock.touch(360)
        self.assertGreater(clock.deadline(),360)
        self.assertEqual(clock.deadline(),360+TURN_IDLE_SECONDS)

    def test_no_activity_still_has_a_bounded_deadline(self):
        clock=TurnClock(20)
        self.assertEqual(clock.deadline(),20+TURN_IDLE_SECONDS)

    def test_repeated_events_cannot_extend_absolute_limit(self):
        clock=TurnClock(20)
        clock.touch(20+TURN_MAX_SECONDS-1)
        self.assertEqual(clock.deadline(),20+TURN_MAX_SECONDS)


if __name__=='__main__':unittest.main()
