"""Hardware-free regression tests for distributed measurement sessions."""
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

try:
    import iio
except (ImportError, OSError):
    import sys
    import types
    fake_iio = types.ModuleType("iio")
    fake_iio.scan_contexts = lambda: {}
    sys.modules["iio"] = fake_iio

from pluto_monitor.dsp.modes import get_mode
from pluto_monitor.nodes.central_server import DistributedRxCoordinator
from pluto_monitor.nodes.rx_node import RxNode, _radio_inventory, _build_status_message


RF = {"center_frequency_hz": 2400000000, "sample_rate_hz": 1000000, "samples_per_frame": 4096,
      "rx_gain_db": 30, "tx_gain_db": -40, "sps": 2, "data_bits": 1024, "tone_frequency_hz": 10000}


def free_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeReceiver:
    """Returns the QPSK waveform, so the whole receive chain runs for real."""

    def __init__(self):
        wave = get_mode("QPSK").build_waveform(RF)
        rng = np.random.default_rng(1)
        iq = np.resize(wave, get_mode("QPSK").capture_samples(RF)) * 100
        self.iq = iq + rng.normal(size=iq.size) + 1j * rng.normal(size=iq.size)
        self.closed = False

    def read_samples(self):
        return self.iq

    def close(self):
        self.closed = True


class DistributedMeasurementsTest(unittest.TestCase):
    def test_tx_off_service_starts_receivers_without_transmitting(self):
        from pluto_monitor.web.server import DistributedService
        cfg = {"network": {"metrics_host": "127.0.0.1", "metrics_port": 0,
                          "receiver_nodes": [{"id": "rxpi1", "group": "A", "host": "localhost"}]},
               "radio": {"serial": "fake"}, "app": {"mode": "SineWave", "update_period_s": 0.5},
               "rf": dict(RF), "runtime": {}}
        with tempfile.TemporaryDirectory() as directory:
            cfg["runtime"]["log_dir"] = directory
            with patch("pluto_monitor.web.server.load_config", return_value=cfg):
                service = DistributedService("unused")
            service.tx = Mock()
            service.coordinator.start_receivers = Mock(return_value={"rxpi1": {"success": True}})
            service.coordinator.stop_receivers = Mock(return_value={"rxpi1": {"success": True}})
            try:
                service.start({"transmit_enabled": False})
                service.tx.start.assert_not_called()
                service.tx.stop.assert_called_once()
                self.assertEqual(service.state, "running")
                service.stop()
                self.assertEqual(service.state, "idle")
                self.assertIsNone(service.coordinator._session_log)
            finally:
                service.coordinator.close()


    def test_session_records_each_measurement_with_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = {"network": {"metrics_host": "127.0.0.1", "metrics_port": 0,
                               "receiver_nodes": [{"id": "rxpi1", "group": "A", "host": "localhost"}]},
                   "runtime": {"log_dir": directory}}
            coordinator = DistributedRxCoordinator(cfg)
            try:
                coordinator.start_session({"mode": "SineWave", "transmit_enabled": False}, {})
                message = {"type": "rx_metrics", "node_id": "rxpi1", "group": "A",
                           "timestamp": 123.5, "sequence": 1, "mode": "SineWave",
                           "radios": [], "summary": {}}
                coordinator._handle_message(message, ("127.0.0.1", 5556))
                snapshot = coordinator.get_metrics()
                self.assertEqual(snapshot["groups"]["A"]["sequence"], 1)
                self.assertEqual(snapshot["groups"]["A"]["timestamp"], 123.5)
                path = Path(coordinator.session_log_path)
                coordinator.end_session()
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertEqual([r["type"] for r in rows], ["session_start", "rx_metrics", "session_end"])
                self.assertFalse(rows[0]["app"]["transmit_enabled"])
                self.assertEqual(rows[1]["session_id"], snapshot["session_id"])
            finally:
                coordinator.close()


    def test_inventory_distinguishes_attached_missing_and_unknown(self):
        config = {"radios": [{"label": "A1", "serial": "ABC"}, {"label": "A2", "serial": "DEF"}]}
        with patch("pluto_monitor.nodes.rx_node.scan_connected_radios", return_value=[
            {"serial": "abc", "uri": "usb:1", "description": "Pluto"},
        ]):
            radios = _radio_inventory(config)
        self.assertEqual([r["connected"] for r in radios], [True, False])
        self.assertEqual(radios[0]["serial"], "abc")
        with patch("pluto_monitor.nodes.rx_node.scan_connected_radios", side_effect=RuntimeError("test failure")):
            self.assertTrue(all(r["connected"] is None for r in _radio_inventory(config)))

    def test_inventory_survives_metric_updates(self):
        config = {"network": {"metrics_host": "127.0.0.1", "metrics_port": 0,
                             "receiver_nodes": [{"id": "rxpi1", "group": "A", "host": "localhost"}]}}
        coordinator = DistributedRxCoordinator(config)
        try:
            radios = [{"label": "A1", "serial": "abc", "connected": True}]
            status = _build_status_message(config={"node": {"id": "rxpi1", "group": "A"}},
                                           state="idle", connected_radios=1, radios=radios)
            coordinator._handle_message(status, ("127.0.0.1", 5556))
            coordinator._handle_message({"type": "rx_metrics", "node_id": "rxpi1", "group": "A",
                                         "timestamp": 123.0, "radios": []}, ("127.0.0.1", 5556))
            self.assertEqual(coordinator.get_node_status()["rxpi1"]["radios"], radios)
        finally:
            coordinator.close()

    def test_node_and_coordinator_exchange_commands_and_metrics(self):
        metrics_port, control_port = free_udp_port(), free_udp_port()
        coordinator = DistributedRxCoordinator({"network": {
            "metrics_host": "127.0.0.1", "metrics_port": metrics_port,
            "receiver_nodes": [{"id": "n1", "group": "A", "host": "127.0.0.1",
                                "control_port": control_port}]}})
        node = RxNode({"node": {"id": "n1", "group": "A"},
                       "app": {"mode": "SineWave", "update_period_s": 0.05}, "rf": dict(RF),
                       "radios": [{"label": "A1", "uri": "usb:1"}],
                       "network": {"central_host": "127.0.0.1", "metrics_port": metrics_port,
                                   "control_host": "127.0.0.1", "control_port": control_port}})
        fake = FakeReceiver()
        stop = threading.Event()

        def loop():
            while not stop.is_set():
                node.step()

        with patch("pluto_monitor.nodes.rx_node.connect_receivers", return_value={"usb:1": fake}), \
             patch("pluto_monitor.nodes.rx_node.scan_connected_radios", return_value=[]):
            thread = threading.Thread(target=loop)
            coordinator.start()
            thread.start()
            try:
                rejected = coordinator.start_receivers(
                    {"mode": "QPSK"}, {"center_frequency_hz": 1}, timeout=5)
                self.assertFalse(rejected["n1"]["success"])
                self.assertIn("center_frequency_hz", rejected["n1"]["error"])
                self.assertTrue(coordinator.start_receivers({"mode": "QPSK"}, {}, timeout=5)["n1"]["success"])
                deadline = time.monotonic() + 5
                while not coordinator.get_metrics()["groups"] and time.monotonic() < deadline:
                    time.sleep(0.02)
                radio = coordinator.get_metrics()["groups"]["A"]["radios"][0]
                self.assertEqual(radio["label"], "A1")
                self.assertEqual(radio["ber"], 0)
                self.assertGreater(radio["snr_db"], 25)
                self.assertTrue(coordinator.stop_receivers(timeout=5)["n1"]["success"])
                self.assertTrue(fake.closed)
            finally:
                stop.set()
                thread.join(timeout=5)
                node.close()
                coordinator.close()

    def test_node_survives_network_errors(self):
        node = RxNode({"node": {"id": "n1", "group": "A"},
                       "app": {"mode": "SineWave", "update_period_s": 0.5}, "rf": dict(RF),
                       "radios": [], "network": {"central_host": "127.0.0.1", "metrics_port": 9,
                                                 "control_host": "127.0.0.1", "control_port": 0}})
        try:
            node.metrics_client = Mock()
            node.metrics_client.send.side_effect = socket.gaierror("name resolution failed")
            with patch("pluto_monitor.nodes.rx_node.scan_connected_radios", return_value=[]):
                node.step()
            node.metrics_client.send.assert_called_once()
        finally:
            node.close()

    def test_unreachable_node_does_not_block_the_others(self):
        coordinator = DistributedRxCoordinator({"network": {
            "metrics_host": "127.0.0.1", "metrics_port": 0,
            "receiver_nodes": [{"id": "gone", "group": "A", "host": "gone.invalid"},
                               {"id": "ok", "group": "B", "host": "127.0.0.1"}]}})
        real = coordinator.sock
        coordinator.sock = Mock()

        def send(payload, address):
            if address[0] == "gone.invalid":
                raise socket.gaierror("unknown host")
            coordinator._handle_message({"type": "rx_command_response", "command": "stop",
                                         "node_id": "ok", "success": True}, ("127.0.0.1", 1))

        coordinator.sock.sendto.side_effect = send
        try:
            responses = coordinator.stop_receivers(timeout=2)
            self.assertFalse(responses["gone"]["success"])
            self.assertTrue(responses["ok"]["success"])
        finally:
            real.close()

    def test_status_stays_available_while_start_waits(self):
        from pluto_monitor.web.server import DistributedService
        cfg = {"network": {"metrics_host": "127.0.0.1", "metrics_port": 0,
                           "receiver_nodes": [{"id": "n1", "group": "A", "host": "localhost"}]},
               "radio": {"serial": "fake"}, "app": {"mode": "SineWave", "update_period_s": 0.5},
               "rf": dict(RF), "runtime": {}}
        with tempfile.TemporaryDirectory() as directory:
            cfg["runtime"]["log_dir"] = directory
            with patch("pluto_monitor.web.server.load_config", return_value=cfg):
                service = DistributedService("unused")
            service.tx = Mock()
            service.tx.status.return_value = {"state": "idle"}
            release = threading.Event()

            def slow(**kwargs):
                release.wait(5)
                return {"n1": {"success": True}}

            service.coordinator.start_receivers = slow
            service.coordinator.stop_receivers = Mock(return_value={"n1": {"success": True}})
            thread = threading.Thread(target=service.start, args=({"transmit_enabled": False},))
            thread.start()
            try:
                time.sleep(0.1)
                before = time.monotonic()
                self.assertEqual(service.status()["state"], "starting")
                self.assertLess(time.monotonic() - before, 0.5)
                with self.assertRaises(RuntimeError):
                    service.start({})
            finally:
                release.set()
                thread.join(timeout=5)
                service.stop()
                service.coordinator.close()

    def test_invalid_settings_never_reach_the_radios(self):
        from pluto_monitor.web.server import DistributedService
        cfg = {"network": {"metrics_host": "127.0.0.1", "metrics_port": 0,
                           "receiver_nodes": [{"id": "n1", "group": "A", "host": "localhost"}]},
               "radio": {"serial": "fake"}, "app": {"mode": "SineWave", "update_period_s": 0.5},
               "rf": dict(RF), "runtime": {}}
        with patch("pluto_monitor.web.server.load_config", return_value=cfg):
            service = DistributedService("unused")
        service.coordinator.start_receivers = Mock()
        try:
            for bad in ({"tx_gain_db": 10}, {"center_frequency_hz": 1}, {"mode": "X"},
                        {"mode": "16QAM", "data_bits": 1023}):
                with self.assertRaises(ValueError):
                    service.start(bad)
            service.coordinator.start_receivers.assert_not_called()
            self.assertEqual(service.state, "idle")
        finally:
            service.coordinator.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
