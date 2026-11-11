import json
import unittest
from unittest.mock import MagicMock, patch

from paho.mqtt.client import MQTTMessage

from psa_car_controller.psa.RemoteClient import MQTT_EVENT_TOPIC, NO_CHARGE_REMAINING_TIME, RemoteClient
from psa_car_controller.psacc.application.charge_control import ChargeControl
from tests.utils import get_rc

VIN = "VIN"


def event(date, soc, rate=0, remaining_time=0, hmi_state=0, mode=2):
    return {"date": date, "vin": VIN, "precond_state": {},
            "charging_state": {"soc_batt": soc, "rate": rate, "remaining_time": remaining_time,
                               "hmi_state": hmi_state, "autonomy_zev": 200, "mode": mode, "available": 1}}


def send(remote_client, payload):
    msg = MQTTMessage(topic=(MQTT_EVENT_TOPIC + VIN).encode("utf-8"))
    msg.payload = json.dumps(payload).encode("utf-8")
    remote_client._on_mqtt_message(None, None, msg)


def client(auto_wakeup=True):
    remote_client = get_rc()
    remote_client.auto_wakeup = auto_wakeup
    remote_client._fix_not_updated_api = MagicMock()
    return remote_client


class TestChargeState(unittest.TestCase):
    def test_keeps_the_charging_state_of_an_event(self):
        remote_client = client()
        send(remote_client, event("2026-11-04T18:20:00Z", 58, rate=14, hmi_state=1, mode=0))
        self.assertEqual({"soc_batt": 58, "rate": 14, "remaining_time": 0, "hmi_state": 1,
                          "autonomy_zev": 200, "mode": 0, "date": "2026-11-04T18:20:00Z"},
                         remote_client.get_charge_state(VIN))

    def test_an_older_event_arriving_later_does_not_replace_a_newer_one(self):
        remote_client = client()
        send(remote_client, event("2026-11-10T23:24:18Z", 94))
        send(remote_client, event("2026-11-10T23:20:18Z", 48))
        self.assertEqual(94, remote_client.get_charge_state(VIN)["soc_batt"])

    def test_a_newer_event_replaces_the_stored_one(self):
        remote_client = client()
        send(remote_client, event("2026-11-04T18:20:00Z", 58))
        send(remote_client, event("2026-11-04T20:20:00Z", 70))
        self.assertEqual(70, remote_client.get_charge_state(VIN)["soc_batt"])

    def test_an_event_without_date_is_not_stored(self):
        remote_client = client()
        payload = event("x", 58)
        del payload["date"]
        send(remote_client, payload)
        self.assertIsNone(remote_client.get_charge_state(VIN))

    def test_unknown_vin_has_no_state(self):
        self.assertIsNone(client().get_charge_state("OTHER"))


class TestIsCharging(unittest.TestCase):
    def test_no_charge_placeholder_is_not_charging(self):
        self.assertFalse(RemoteClient.is_charging({"rate": 0, "remaining_time": NO_CHARGE_REMAINING_TIME}))

    def test_zero_is_not_charging(self):
        self.assertFalse(RemoteClient.is_charging({"rate": 0, "remaining_time": 0}))

    def test_a_rate_is_charging(self):
        self.assertTrue(RemoteClient.is_charging({"rate": 14, "remaining_time": 0}))

    def test_a_real_estimate_is_charging(self):
        self.assertTrue(RemoteClient.is_charging({"rate": 0, "remaining_time": 205}))

    def test_missing_values_are_not_charging(self):
        self.assertFalse(RemoteClient.is_charging({}))
        self.assertFalse(RemoteClient.is_charging(None))


class TestAutoWakeup(unittest.TestCase):
    def charging_api_not_updated(self, auto_wakeup):
        remote_client = get_rc()
        remote_client.auto_wakeup = auto_wakeup
        remote_client.wakeup = MagicMock()
        car = MagicMock()
        car.status.get_energy.return_value.charging.status = "Disconnected"
        remote_client.vehicles_list = MagicMock()
        remote_client.vehicles_list.get_car_by_vin.return_value = car
        return remote_client

    @patch('time.sleep', return_value=None)
    def test_no_charge_placeholder_does_not_wake_the_car(self, _sleep):
        remote_client = self.charging_api_not_updated(True)
        remote_client._fix_not_updated_api({"rate": 0, "remaining_time": NO_CHARGE_REMAINING_TIME}, VIN)
        remote_client.wakeup.assert_not_called()

    @patch('time.sleep', return_value=None)
    def test_a_running_charge_wakes_the_car(self, _sleep):
        remote_client = self.charging_api_not_updated(True)
        remote_client._fix_not_updated_api({"rate": 14, "remaining_time": 120}, VIN)
        remote_client.wakeup.assert_called_once_with(VIN)

    @patch('time.sleep', return_value=None)
    def test_switched_off_never_wakes_the_car(self, _sleep):
        remote_client = self.charging_api_not_updated(False)
        remote_client._fix_not_updated_api({"rate": 14, "remaining_time": 120}, VIN)
        remote_client.wakeup.assert_not_called()

    def test_switch_reads_the_environment(self):
        with patch.dict("os.environ", {"PSACC_AUTO_WAKEUP": "0"}):
            self.assertFalse(get_rc().auto_wakeup)
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(get_rc().auto_wakeup)

    def test_keepalive_only_refreshes_the_token_when_switched_off(self):
        remote_client = get_rc()
        remote_client.auto_wakeup = False
        remote_client.vehicles_list = [MagicMock(vin=VIN)]
        remote_client.wakeup = MagicMock()
        remote_client._refresh_remote_token = MagicMock()
        with patch("threading.Timer"):
            remote_client._RemoteClient__keep_mqtt()
        remote_client.wakeup.assert_not_called()
        remote_client._refresh_remote_token.assert_called_once_with()

    def test_keepalive_wakes_the_car_when_switched_on(self):
        remote_client = get_rc()
        remote_client.auto_wakeup = True
        remote_client.vehicles_list = [MagicMock(vin=VIN)]
        remote_client.wakeup = MagicMock()
        with patch("threading.Timer"):
            remote_client._RemoteClient__keep_mqtt()
        remote_client.wakeup.assert_called_once_with(VIN)

    def test_charge_control_does_not_wake_when_switched_off(self):
        psacc = MagicMock()
        psacc.remote_client.auto_wakeup = False
        ChargeControl(psacc, VIN, 80, None).force_update(MagicMock())
        psacc.remote_client.wakeup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
