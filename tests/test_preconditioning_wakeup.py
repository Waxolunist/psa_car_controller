import unittest
from unittest.mock import MagicMock, call

from psa_car_controller.common.utils import RateLimitException
from psa_car_controller.psa.RemoteClient import RemoteClient


def get_client() -> RemoteClient:
    client = RemoteClient.__new__(RemoteClient)
    client.precond_programs = {}
    client.mqtt_request = MagicMock(side_effect=lambda vin, req, topic: topic)
    client.publish = MagicMock()
    client.wakeup = MagicMock()
    return client


class TestPreconditioningWakeup(unittest.TestCase):

    def test_without_wakeup_only_the_preconditioning_is_sent(self):
        client = get_client()
        client.preconditioning("VIN", True)
        client.wakeup.assert_not_called()
        client.publish.assert_called_once_with("/ThermalPrecond")

    def test_wakeup_is_sent_before_the_preconditioning(self):
        client = get_client()
        calls = MagicMock()
        calls.attach_mock(client.wakeup, "wakeup")
        calls.attach_mock(client.publish, "publish")
        client.preconditioning("VIN", True, wakeup=True)
        self.assertEqual([call.wakeup("VIN"), call.publish("/ThermalPrecond")], calls.mock_calls)

    def test_a_rate_limited_wakeup_still_sends_the_preconditioning(self):
        client = get_client()
        client.wakeup.side_effect = RateLimitException("wakeup")
        with self.assertLogs("psa_car_controller.psa.RemoteClient", "WARNING"):
            client.preconditioning("VIN", False, wakeup=True)
        client.publish.assert_called_once_with("/ThermalPrecond")


if __name__ == '__main__':
    unittest.main()
