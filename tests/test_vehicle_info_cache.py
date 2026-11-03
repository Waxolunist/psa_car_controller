import unittest
from unittest.mock import MagicMock

from psa_car_controller.psa.connected_car_api.rest import ApiException
from psa_car_controller.psacc.application.psa_client import PSAClient


def get_client(status=None) -> PSAClient:
    client = PSAClient.__new__(PSAClient)  # bypass __init__, it does I/O
    car = MagicMock(status=status)
    client.vehicles_list = MagicMock()
    client.vehicles_list.get_car_by_vin.return_value = car
    client.api = MagicMock()
    client.remote_client = MagicMock()
    client._record_enabled = False
    return client


class TestVehicleInfoCache(unittest.TestCase):

    def test_a_cached_read_returns_the_stored_status(self):
        status = MagicMock()
        client = get_client(status)
        self.assertIs(status, client.get_vehicle_info("VIN", cache=True))
        client.api.assert_not_called()

    def test_a_cached_read_with_an_empty_cache_does_not_call_psa(self):
        client = get_client()
        self.assertIsNone(client.get_vehicle_info("VIN", cache=True))
        client.api.assert_not_called()

    def test_a_failed_refresh_empties_the_cache(self):
        client = get_client(MagicMock())
        client.api.return_value.get_vehicle_status.side_effect = ApiException(status=500)
        self.assertIsNone(client.get_vehicle_info("VIN"))
        self.assertEqual(2, client.api.return_value.get_vehicle_status.call_count)
        self.assertIsNone(client.get_vehicle_info("VIN", cache=True))


if __name__ == '__main__':
    unittest.main()
