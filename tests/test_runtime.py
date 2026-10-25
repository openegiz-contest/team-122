import itertools
import unittest
from unittest.mock import Mock, patch
from app.server import Runtime


class RuntimeTests(unittest.TestCase):
    def test_platform_retry_does_not_accelerate_simulated_time(self):
        runtime=Runtime()
        runtime.platform=Mock(client=None)
        runtime.platform.setup.side_effect=RuntimeError("not ready")
        sleeps=[]
        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps)==4:
                runtime.running=False
        clock=itertools.count(step=.01)
        with patch("app.server.time.monotonic",side_effect=lambda:next(clock)), patch("app.server.time.sleep",side_effect=sleep):
            runtime.loop()
        self.assertEqual(runtime.twin.time,20)
        self.assertGreaterEqual(sum(sleeps),3.5)
        runtime.platform.setup.assert_called_once()
        runtime.platform.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
