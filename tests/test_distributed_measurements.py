"""Hardware-free regression tests for distributed measurement sessions."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

try:
    import iio
except (ImportError, OSError):
    import sys
    import types
    fake_iio = types.ModuleType("iio")
    fake_iio.scan_contexts = lambda: {}
    sys.modules["iio"] = fake_iio

from pluto_monitor.nodes.central_server import DistributedRxCoordinator
from pluto_monitor.nodes.rx_node import _build_runtime_config, _radio_inventory, _build_status_message


class DistributedMeasurementsTest(unittest.TestCase):
    def test_digital_buffer_contains_full_cyclic_frames(self):
        base = {"app": {"mode": "BPSK", "update_period_s": 0.5},
                "rf": {"center_frequency_hz": 2400000000, "sample_rate_hz": 1000000,
                       "samples_per_frame": 4096, "sps": 2, "data_bits": 4096}}
        cfg = _build_runtime_config(base, {})
        self.assertGreaterEqual(cfg["rf"]["samples_per_frame"], 2 * (4096 + 39) * 2)
        self.assertEqual(base["rf"]["samples_per_frame"], 4096)


    def test_tx_off_service_starts_receivers_without_transmitting(self):
        from pluto_monitor.web.server import DistributedService
        cfg = {"network": {"metrics_host": "127.0.0.1", "metrics_port": 0,
                          "receiver_nodes": [{"id": "rxpi1", "group": "A", "host": "localhost"}]},
               "radio": {"serial": "fake"}, "app": {"mode": "SineWave", "update_period_s": 0.5},
               "rf": {}, "runtime": {}}
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
