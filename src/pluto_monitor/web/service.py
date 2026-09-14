from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from pluto_monitor.app import build_receivers, build_transmitter, build_tx_waveform
from pluto_monitor.config.loader import load_config
from pluto_monitor.hardware.discovery import resolve_topology, validate_required_radios
from pluto_monitor.hardware.receiver import PlutoReceiver
from pluto_monitor.hardware.transmitter import PlutoTransmitter
from pluto_monitor.models.history import MetricHistory
from pluto_monitor.services.acquisition import AcquisitionResult, acquire_once

VALID_MODES = {"SineWave", "BPSK", "QPSK", "16QAM"}

_RF_INT_FIELDS = ("center_frequency_hz", "sample_rate_hz", "sps", "data_bits")
_RF_FLOAT_FIELDS = ("rx_gain_db", "tx_gain_db", "tone_frequency_hz")


class ServiceStateError(RuntimeError):
    """Raised when an operation is invalid for the service's current state."""


@dataclass
class ServiceStatus:
    state: str  # "idle" | "starting" | "running" | "stopping" | "error"
    mode: Optional[str] = None
    error: Optional[str] = None
    connected_radios: list[str] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)


def _safe_float(value: Any) -> Optional[float]:
    """Convert to a JSON-safe float, turning NaN/inf/garbage into None.

    Plain json/WebSocket serialization would otherwise emit a literal
    `NaN`, which is not valid JSON and breaks `JSON.parse` in the browser.
    """
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN
        return None
    if parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _apply_overrides(config: dict[str, Any], overrides: dict[str, Any]) -> None:
    """Apply optional UI overrides on top of a freshly loaded YAML config.

    Radio wiring (which serials belong to which group, transmitter serial)
    intentionally stays in the YAML file for now; only RF/mode/timing
    parameters are adjustable from the web UI in this first version.
    """
    mode = overrides.get("mode")
    if mode is not None:
        if mode not in VALID_MODES:
            raise ValueError(
                f"Unsupported mode '{mode}'. Valid modes: {sorted(VALID_MODES)}"
            )
        config["app"]["mode"] = mode

    update_period_s = overrides.get("update_period_s")
    if update_period_s is not None:
        update_period_s = float(update_period_s)
        if update_period_s <= 0:
            raise ValueError("update_period_s must be > 0")
        config["app"]["update_period_s"] = update_period_s

    rf = config["rf"]

    for field_name in _RF_INT_FIELDS:
        value = overrides.get(field_name)
        if value is not None:
            rf[field_name] = int(value)

    for field_name in _RF_FLOAT_FIELDS:
        value = overrides.get(field_name)
        if value is not None:
            rf[field_name] = float(value)


def _result_to_json(
    result: AcquisitionResult,
    radio_labels: dict[str, str],
) -> dict[str, Any]:
    groups: dict[str, Any] = {}

    for group_name, power_map in result.group_powers.items():
        snr_map = result.group_snrs.get(group_name, {})
        summary = result.group_summaries.get(group_name)

        radios = []
        for radio_uri, power_db in power_map.items():
            radios.append(
                {
                    "uri": radio_uri,
                    "serial": radio_labels.get(radio_uri),
                    "power_db": _safe_float(power_db),
                    "snr_db": _safe_float(snr_map.get(radio_uri)),
                    "is_strongest": bool(
                        summary is not None and radio_uri == summary.strongest_label
                    ),
                    "is_weakest": bool(
                        summary is not None and radio_uri == summary.weakest_label
                    ),
                }
            )

        groups[group_name] = {
            "radios": radios,
            "mean_power_db": _safe_float(result.group_mean_power_db.get(group_name)),
            "mean_noise_db": _safe_float(result.group_mean_noise_db.get(group_name)),
            "strongest_label": summary.strongest_label if summary else None,
            "strongest_db": _safe_float(summary.strongest_db) if summary else None,
            "weakest_label": summary.weakest_label if summary else None,
            "weakest_db": _safe_float(summary.weakest_db) if summary else None,
        }

    return {
        "timestamp": result.timestamp,
        "strongest_group": result.strongest_group,
        "groups": groups,
    }


class AcquisitionService:
    """Owns the lifecycle of locally-connected Pluto hardware.

    This mirrors `pluto_monitor.app.run_continuous`, but instead of
    printing to stdout and blocking forever, it runs the acquisition loop
    on a background thread and keeps the latest result in memory so a web
    layer can poll/broadcast it. All hardware I/O happens on that single
    thread so pyadi-iio's blocking calls never block the asyncio event
    loop used by FastAPI/uvicorn.
    """

    def __init__(self, config_path: str = "configs/default.yaml") -> None:
        self._config_path = config_path
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._state = "idle"
        self._error: Optional[str] = None

        self._config: dict[str, Any] = {}
        self._receivers: dict[str, PlutoReceiver] = {}
        self._transmitter: Optional[PlutoTransmitter] = None
        self._resolved_groups: dict[str, list[str]] = {}
        self._radio_labels: dict[str, str] = {}

        self._mode: Optional[str] = None
        self._latest_result: Optional[AcquisitionResult] = None
        self._history = MetricHistory()

    # ---- config -------------------------------------------------------

    def load_base_config(self) -> dict[str, Any]:
        return load_config(self._config_path)

    # ---- status / data for the API -------------------------------------

    def get_status(self) -> ServiceStatus:
        with self._lock:
            return ServiceStatus(
                state=self._state,
                mode=self._mode,
                error=self._error,
                connected_radios=list(self._receivers.keys()),
                groups={k: list(v) for k, v in self._resolved_groups.items()},
            )

    def get_snapshot(self) -> Optional[dict[str, Any]]:
        with self._lock:
            if self._latest_result is None:
                return None
            return _result_to_json(self._latest_result, dict(self._radio_labels))

    # ---- lifecycle ------------------------------------------------------

    def start(self, overrides: dict[str, Any]) -> None:
        with self._lock:
            if self._state in ("starting", "running"):
                raise ServiceStateError(f"Service already {self._state}")
            self._state = "starting"
            self._error = None

        try:
            config = self.load_base_config()
            _apply_overrides(config, overrides)
            validate_required_radios(config)
            resolved = resolve_topology(config)

            receivers, resolved_groups = build_receivers(config, resolved)
            transmitter = build_transmitter(config, resolved)
            mode, _tx_debug = build_tx_waveform(transmitter, config)

            radio_labels = {
                uri: serial for serial, uri in resolved.serial_to_uri.items()
            }

            with self._lock:
                self._config = config
                self._receivers = receivers
                self._transmitter = transmitter
                self._resolved_groups = resolved_groups
                self._radio_labels = radio_labels
                self._mode = mode
                self._latest_result = None
                self._history = MetricHistory(
                    max_points=int(config["runtime"].get("max_history_points", 100))
                )

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop, name="pluto-acquisition", daemon=True
            )
            self._thread.start()

            with self._lock:
                self._state = "running"

        except Exception as exc:
            with self._lock:
                self._state = "error"
                self._error = str(exc)
            self._cleanup_hardware()
            raise

    def stop(self) -> None:
        with self._lock:
            if self._state not in ("running", "error"):
                raise ServiceStateError(
                    f"Service is not running (state={self._state})"
                )
            self._state = "stopping"

        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)

        self._cleanup_hardware()

        with self._lock:
            self._state = "idle"
            self._thread = None
            self._mode = None
            self._latest_result = None

    def _cleanup_hardware(self) -> None:
        with self._lock:
            receivers = list(self._receivers.values())
            transmitter = self._transmitter
            self._receivers = {}
            self._transmitter = None

        for receiver in receivers:
            try:
                receiver.close()
            except Exception:
                pass

        if transmitter is not None:
            try:
                transmitter.close()
            except Exception:
                pass

    def _run_loop(self) -> None:
        with self._lock:
            config = self._config
            resolved_groups = dict(self._resolved_groups)
            receivers = dict(self._receivers)
            mode = self._mode

        acquisition_groups = {
            group_name: {"radio_ids": uris}
            for group_name, uris in resolved_groups.items()
        }
        update_period_s = float(config["app"]["update_period_s"])

        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                result = acquire_once(
                    groups=acquisition_groups,
                    receivers=receivers,
                    mode=mode,
                    rf_config=config["rf"],
                )
            except Exception as exc:  # keep the thread from dying silently
                with self._lock:
                    self._state = "error"
                    self._error = str(exc)
                return

            with self._lock:
                self._latest_result = result
                self._history.append(result.timestamp, result.group_summaries)

            elapsed = time.monotonic() - t0
            self._stop_event.wait(max(0.0, update_period_s - elapsed))
