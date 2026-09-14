"""Unit tests for pluto_monitor.web.service.

These tests never touch real hardware. `iio`/`adi` are stubbed out so the
module import chain (service -> app -> hardware.discovery) works even on
machines without pyadi-iio installed (e.g. CI). The AcquisitionService
lifecycle is exercised by monkeypatching the hardware-building functions
it imports from `pluto_monitor.app`.
"""

from __future__ import annotations

import sys
import types

import pytest

# --- stub out hardware-only modules before importing pluto_monitor.web ---

if "iio" not in sys.modules:
    fake_iio = types.ModuleType("iio")
    fake_iio.scan_contexts = lambda: {}
    sys.modules["iio"] = fake_iio

if "adi" not in sys.modules:
    fake_adi = types.ModuleType("adi")

    class _FakePluto:
        def __init__(self, *args, **kwargs) -> None:
            pass

    fake_adi.Pluto = _FakePluto
    sys.modules["adi"] = fake_adi

from pluto_monitor.hardware.discovery import ResolvedRadioTopology
from pluto_monitor.services.acquisition import AcquisitionResult
from pluto_monitor.services.clustering import GroupSummary
from pluto_monitor.web import service as service_module
from pluto_monitor.web.service import (
    AcquisitionService,
    ServiceStateError,
    _apply_overrides,
    _result_to_json,
    _safe_float,
)


# --- _safe_float -------------------------------------------------------


def test_safe_float_passes_through_normal_values() -> None:
    assert _safe_float(3.5) == 3.5


def test_safe_float_converts_nan_to_none() -> None:
    assert _safe_float(float("nan")) is None


def test_safe_float_converts_inf_to_none() -> None:
    assert _safe_float(float("inf")) is None
    assert _safe_float(float("-inf")) is None


def test_safe_float_handles_none_input() -> None:
    assert _safe_float(None) is None


# --- _apply_overrides ----------------------------------------------------


def _base_config() -> dict:
    return {
        "app": {"mode": "SineWave", "update_period_s": 0.5},
        "rf": {
            "center_frequency_hz": 2_400_000_000,
            "sample_rate_hz": 1_000_000,
            "samples_per_frame": 4096,
            "rx_gain_db": 30,
            "tx_gain_db": -12,
            "sps": 2,
            "data_bits": 4096,
            "tone_frequency_hz": 10_000,
        },
    }


def test_apply_overrides_updates_mode_and_rf_fields() -> None:
    config = _base_config()
    _apply_overrides(
        config,
        {"mode": "BPSK", "rx_gain_db": 40, "center_frequency_hz": 2_450_000_000},
    )
    assert config["app"]["mode"] == "BPSK"
    assert config["rf"]["rx_gain_db"] == 40.0
    assert config["rf"]["center_frequency_hz"] == 2_450_000_000


def test_apply_overrides_rejects_invalid_mode() -> None:
    config = _base_config()
    with pytest.raises(ValueError):
        _apply_overrides(config, {"mode": "NOT_A_MODE"})


def test_apply_overrides_rejects_non_positive_update_period() -> None:
    config = _base_config()
    with pytest.raises(ValueError):
        _apply_overrides(config, {"update_period_s": 0})


def test_apply_overrides_leaves_config_untouched_when_no_overrides() -> None:
    config = _base_config()
    original = _base_config()
    _apply_overrides(config, {})
    assert config == original


# --- _result_to_json -----------------------------------------------------


def test_result_to_json_flags_strongest_and_weakest_and_hides_nan() -> None:
    result = AcquisitionResult(
        timestamp=123.0,
        group_powers={"A": {"usb:1.1": -30.0, "usb:1.2": -50.0}},
        group_snrs={"A": {"usb:1.1": 20.0, "usb:1.2": float("nan")}},
        group_summaries={
            "A": GroupSummary(
                strongest_label="usb:1.1",
                strongest_db=-30.0,
                weakest_label="usb:1.2",
                weakest_db=-50.0,
            )
        },
        strongest_group="A",
        group_mean_power_db={"A": -40.0},
        group_mean_noise_db={"A": float("nan")},
    )

    payload = _result_to_json(result, radio_labels={"usb:1.1": "serial-1", "usb:1.2": "serial-2"})

    assert payload["strongest_group"] == "A"
    group_a = payload["groups"]["A"]
    assert group_a["mean_power_db"] == -40.0
    assert group_a["mean_noise_db"] is None  # NaN -> None

    radios_by_uri = {r["uri"]: r for r in group_a["radios"]}
    assert radios_by_uri["usb:1.1"]["is_strongest"] is True
    assert radios_by_uri["usb:1.1"]["is_weakest"] is False
    assert radios_by_uri["usb:1.1"]["serial"] == "serial-1"
    assert radios_by_uri["usb:1.2"]["is_weakest"] is True
    assert radios_by_uri["usb:1.2"]["snr_db"] is None  # NaN -> None


# --- AcquisitionService lifecycle (hardware fully mocked) ----------------


class _FakeReceiver:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeTransmitter:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _canned_result() -> AcquisitionResult:
    return AcquisitionResult(
        timestamp=1.0,
        group_powers={"A": {"uri1": -30.0}},
        group_snrs={"A": {"uri1": 15.0}},
        group_summaries={
            "A": GroupSummary("uri1", -30.0, "uri1", -30.0)
        },
        strongest_group="A",
        group_mean_power_db={"A": -30.0},
        group_mean_noise_db={"A": -45.0},
    )


@pytest.fixture()
def patched_service(monkeypatch: pytest.MonkeyPatch) -> AcquisitionService:
    svc = AcquisitionService(config_path="unused.yaml")

    fake_config = {
        "app": {"mode": "SineWave", "update_period_s": 0.01},
        "rf": {
            "center_frequency_hz": 2_400_000_000,
            "sample_rate_hz": 1_000_000,
            "samples_per_frame": 4096,
            "rx_gain_db": 30,
            "tx_gain_db": -12,
            "sps": 2,
            "data_bits": 4096,
            "tone_frequency_hz": 10_000,
        },
        "runtime": {"max_history_points": 10},
    }

    monkeypatch.setattr(svc, "load_base_config", lambda: dict(fake_config))
    monkeypatch.setattr(service_module, "validate_required_radios", lambda config: None)
    monkeypatch.setattr(
        service_module,
        "resolve_topology",
        lambda config: ResolvedRadioTopology(
            receiver_uris=["uri1"],
            transmitter_uri="uri_tx",
            serial_to_uri={"serial1": "uri1", "serial_tx": "uri_tx"},
        ),
    )
    monkeypatch.setattr(
        service_module,
        "build_receivers",
        lambda config, resolved: ({"uri1": _FakeReceiver()}, {"A": ["uri1"]}),
    )
    monkeypatch.setattr(
        service_module, "build_transmitter", lambda config, resolved: _FakeTransmitter()
    )
    monkeypatch.setattr(
        service_module, "build_tx_waveform", lambda transmitter, config: ("SineWave", None)
    )
    monkeypatch.setattr(service_module, "acquire_once", lambda **kwargs: _canned_result())

    return svc


def test_start_transitions_to_running(patched_service: AcquisitionService) -> None:
    patched_service.start({})
    status = patched_service.get_status()
    assert status.state == "running"
    assert status.mode == "SineWave"
    assert status.connected_radios == ["uri1"]
    assert status.groups == {"A": ["uri1"]}
    patched_service.stop()


def test_start_twice_raises(patched_service: AcquisitionService) -> None:
    patched_service.start({})
    with pytest.raises(ServiceStateError):
        patched_service.start({})
    patched_service.stop()


def test_stop_without_start_raises(patched_service: AcquisitionService) -> None:
    with pytest.raises(ServiceStateError):
        patched_service.stop()


def test_stop_cleans_up_and_returns_idle(patched_service: AcquisitionService) -> None:
    patched_service.start({})
    patched_service.stop()
    status = patched_service.get_status()
    assert status.state == "idle"
    assert status.connected_radios == []


def test_snapshot_becomes_available_after_start(patched_service: AcquisitionService) -> None:
    patched_service.start({})
    import time

    # Give the background thread a brief moment to run at least once.
    for _ in range(50):
        if patched_service.get_snapshot() is not None:
            break
        time.sleep(0.01)

    snapshot = patched_service.get_snapshot()
    assert snapshot is not None
    assert snapshot["strongest_group"] == "A"
    patched_service.stop()


def test_start_failure_marks_error_state_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, patched_service: AcquisitionService
) -> None:
    def _boom(config, resolved):
        raise RuntimeError("no radios connected")

    monkeypatch.setattr(service_module, "build_receivers", _boom)

    with pytest.raises(RuntimeError):
        patched_service.start({})

    status = patched_service.get_status()
    assert status.state == "error"
    assert "no radios connected" in status.error
