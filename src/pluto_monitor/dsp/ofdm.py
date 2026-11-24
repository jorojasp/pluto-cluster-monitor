"""Coded OFDM with an IEEE 802.11-like frame.

Frame: short training field (STF), long training field (LTF) and data symbols.
64 subcarriers, 16-sample cyclic prefix, 48 data and 4 pilot subcarriers, null
DC. The payload is fixed and known, so BER is measured before and after FEC.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Any

import numpy as np
from scipy import signal

from pluto_monitor.dsp import fec
from pluto_monitor.dsp.single_carrier import Modulation, payload_bits

N_FFT = 64
N_CP = 16
SYMBOL = N_FFT + N_CP
STF_LEN = 160
LTF_LEN = 160
PREAMBLE_LEN = STF_LEN + LTF_LEN
# FFT windows start early inside the cyclic prefix to tolerate timing errors.
BACKOFF = 4
MIN_STF_METRIC = 0.1
MIN_LTF_CORR = 0.45
EPS = 1e-12

USED = np.concatenate([np.arange(-26, 0), np.arange(1, 27)])
PILOTS = np.array([-21, -7, 7, 21])
DATA = np.array([k for k in USED if k not in PILOTS])
_PILOT_IN_USED = np.searchsorted(USED, PILOTS)
_DATA_IN_USED = np.searchsorted(USED, DATA)
_PILOT_VALUES = np.array([1.0, 1.0, 1.0, -1.0])

_LTF_LEFT = [1, 1, -1, -1, 1, 1, -1, 1, -1, 1, 1, 1, 1, 1, 1, -1, -1, 1, 1, -1, 1, -1, 1, 1, 1, 1]
_LTF_RIGHT = [1, -1, -1, 1, 1, -1, 1, -1, 1, -1, -1, -1, -1, -1, 1, 1, -1, -1, 1, -1, 1, -1, 1, 1, 1, 1]
LTF_VALUES = np.array(_LTF_LEFT + _LTF_RIGHT, dtype=np.float64)
_STF_BINS = {-24: 1, -20: -1, -16: 1, -12: -1, -8: -1, -4: 1, 4: -1, 8: -1, 12: 1, 16: 1, 20: 1, 24: 1}


def _to_time(values: np.ndarray, bins: np.ndarray) -> np.ndarray:
    """OFDM symbols (last axis: subcarriers) as unit-power time samples."""
    grid = np.zeros(values.shape[:-1] + (N_FFT,), dtype=np.complex128)
    grid[..., bins] = values
    return np.fft.ifft(grid, axis=-1) * N_FFT / np.sqrt(USED.size)


def _preamble() -> np.ndarray:
    bins = np.array(list(_STF_BINS))
    stf_values = np.array(list(_STF_BINS.values())) * (1 + 1j) * np.sqrt(13 / 6)
    stf = np.tile(_to_time(stf_values, bins), 3)[:STF_LEN]
    ltf = _to_time(LTF_VALUES, USED)
    return np.concatenate([stf, ltf[-32:], ltf, ltf])


PREAMBLE = _preamble()
_LTF_TIME = PREAMBLE[-N_FFT:]


def _channel_prior() -> np.ndarray:
    """Covariance of the used subcarriers for delays anywhere in the prefix."""
    delta = (USED[:, None] - USED[None, :]) / N_FFT
    return np.exp(-1j * np.pi * delta * N_CP) * np.sinc(delta * N_CP)


_PRIOR = _channel_prior()


@dataclass(frozen=True, eq=False)
class OfdmFrame:
    """Everything both ends know about a frame."""

    modulation: Modulation
    data_bits: int

    @cached_property
    def message(self) -> np.ndarray:
        return fec.append_crc(payload_bits(self.data_bits))

    @property
    def bits_per_symbol(self) -> int:
        return DATA.size * self.modulation.bits_per_symbol

    @property
    def symbols(self) -> int:
        coded = fec.coded_length(self.data_bits + fec.CRC_BITS)
        return -(-coded // self.bits_per_symbol)

    @property
    def samples(self) -> int:
        return PREAMBLE_LEN + self.symbols * SYMBOL

    @cached_property
    def coded(self) -> np.ndarray:
        """Coded bits padded with known bits to whole OFDM symbols."""
        bits = fec.encode(self.message)
        padding = payload_bits(self.symbols * self.bits_per_symbol - bits.size)
        return np.concatenate([bits, padding])

    @cached_property
    def permutation(self) -> np.ndarray:
        return fec.interleaver(self.coded.size)

    @cached_property
    def transmitted_bits(self) -> np.ndarray:
        return self.coded[self.permutation]

    @cached_property
    def pilots(self) -> np.ndarray:
        """Pilot values (symbol, pilot) with a pseudo-random sign per symbol."""
        signs = 1.0 - 2.0 * np.random.default_rng(127).integers(0, 2, self.symbols)
        return signs[:, None] * _PILOT_VALUES

    @cached_property
    def data(self) -> np.ndarray:
        return self.modulation.modulate(self.transmitted_bits).reshape(self.symbols, DATA.size)

    @cached_property
    def grid(self) -> np.ndarray:
        values = np.empty((self.symbols, USED.size), dtype=np.complex128)
        values[:, _DATA_IN_USED] = self.data
        values[:, _PILOT_IN_USED] = self.pilots
        return values

    def waveform(self) -> np.ndarray:
        body = _to_time(self.grid, USED)
        with_prefix = np.concatenate([body[:, -N_CP:], body], axis=1)
        return np.concatenate([PREAMBLE, with_prefix.ravel()]).astype(np.complex64)


def papr_db(waveform: np.ndarray) -> float:
    power = np.abs(waveform) ** 2
    return float(10 * np.log10(power.max() / power.mean()))


def _detect(iq: np.ndarray, last_start: int) -> tuple[int, float] | None:
    """Return (preamble start, CFO in cycles per sample), or None."""
    lag, window = 16, STF_LEN - 16
    product = np.conj(iq[:-lag]) * iq[lag:]
    ones = np.ones(window)
    corr = signal.fftconvolve(product, ones, mode="valid")
    energy = np.abs(iq) ** 2
    early = signal.fftconvolve(energy[:-lag], ones, mode="valid")
    late = signal.fftconvolve(energy[lag:], ones, mode="valid")
    metric = np.abs(corr) ** 2 / np.maximum(early * late, EPS)
    metric = metric[: last_start + 1]
    coarse = int(np.argmax(metric))
    if metric[coarse] < MIN_STF_METRIC:
        return None
    cfo = float(np.angle(corr[coarse]) / (2 * np.pi * lag))

    # Exact timing from both LTF copies around the expected position.
    expected = coarse + STF_LEN + 32
    begin = max(expected - 64, 0)
    part = iq[begin : expected + 64 + 2 * N_FFT]
    if part.size < 2 * N_FFT + 1:
        return None
    part = part * np.exp(-2j * np.pi * cfo * np.arange(part.size))
    template = np.concatenate([_LTF_TIME, _LTF_TIME])
    matches = np.abs(signal.correlate(part, template, mode="valid"))
    power = signal.fftconvolve(np.abs(part) ** 2, np.ones(template.size), mode="valid")
    score = matches / np.sqrt(np.maximum(power, EPS) * np.sum(np.abs(template) ** 2))
    best = int(np.argmax(score))
    start = begin + best - STF_LEN - 32
    if score[best] < MIN_LTF_CORR or not 0 <= start <= last_start:
        return None
    first = part[best : best + N_FFT]
    second = part[best + N_FFT : best + 2 * N_FFT]
    cfo += float(np.angle(np.vdot(first, second)) / (2 * np.pi * N_FFT))
    return start, cfo


def _spectrum(iq: np.ndarray, start: int) -> np.ndarray:
    """Used subcarriers of one FFT window, with the backoff phase removed."""
    window = iq[start - BACKOFF : start - BACKOFF + N_FFT]
    return np.fft.fft(window)[USED] * np.sqrt(USED.size) / N_FFT


def _estimate_channel(iq: np.ndarray, start: int) -> tuple[np.ndarray, float]:
    """LMMSE channel estimate on the used subcarriers and noise variance."""
    first = _spectrum(iq, start + STF_LEN + 32) * LTF_VALUES
    second = _spectrum(iq, start + STF_LEN + 32 + N_FFT) * LTF_VALUES
    noise = float(np.mean(np.abs(first - second) ** 2) / 2)
    raw = (first + second) / 2
    power = max(float(np.mean(np.abs(raw) ** 2)) - noise / 2, EPS)
    weights = np.linalg.solve(
        _PRIOR + (noise / 2 / power + 1e-4) * np.eye(USED.size), raw
    )
    return _PRIOR @ weights, max(noise, EPS)


def _track(grid: np.ndarray, channel: np.ndarray, pilots: np.ndarray) -> np.ndarray:
    """Phase correction (symbol, subcarrier) for residual CFO and clock offset."""
    reference = channel[_PILOT_IN_USED] * pilots
    z = grid[:, _PILOT_IN_USED] * np.conj(reference)
    index = np.arange(grid.shape[0], dtype=np.float64)
    phase = np.unwrap(np.angle(z.sum(axis=1)))
    smooth = np.empty_like(phase)
    for i in range(phase.size):
        lo, hi = max(0, i - 3), min(phase.size, i + 4)
        if hi - lo < 2:
            smooth[i] = phase[i]
            continue
        smooth[i] = np.polyval(np.polyfit(index[lo:hi] - i, phase[lo:hi], 1), 0.0)
    # A clock offset rotates subcarrier k of symbol s in proportion to k*s.
    slope = np.angle(z * np.exp(-1j * smooth)[:, None])
    regressor = index[:, None] * PILOTS[None, :]
    weight = np.abs(z)
    tilt = np.sum(weight * regressor * slope) / max(np.sum(weight * regressor**2), EPS)
    return smooth[:, None] + tilt * index[:, None] * USED[None, :]


def soft_bits(
    symbols: np.ndarray, modulation: Modulation, noise: np.ndarray | float
) -> np.ndarray:
    """Max-log bit LLRs (positive means 0) of equalized symbols."""
    metric = -np.abs(symbols[:, None] - modulation.constellation[None, :]) ** 2
    labels = np.arange(modulation.constellation.size)
    llr = np.empty((symbols.size, modulation.bits_per_symbol))
    for bit in range(modulation.bits_per_symbol):
        one = (labels >> (modulation.bits_per_symbol - 1 - bit)) & 1 == 1
        llr[:, bit] = metric[:, ~one].max(axis=1) - metric[:, one].max(axis=1)
    return (llr / np.broadcast_to(noise, symbols.shape)[:, None]).ravel()


def _empty(total: float) -> dict[str, Any]:
    nan = float("nan")
    known = np.isfinite(total)
    return {
        "signal_power": total,
        "power_db": float(10 * np.log10(total + EPS)) if known else nan,
        "noise_power": nan, "noise_db": nan, "snr_db": nan, "ber": nan,
        "ber_coded": nan, "frame_ok": nan, "throughput_bps": nan, "cfo_hz": nan,
    }


def analyze(frame: OfdmFrame, iq: np.ndarray, sample_rate_hz: float) -> dict[str, Any]:
    """Receive one frame.

    ber: hard decisions before FEC. ber_coded: payload after FEC. frame_ok: 1
    when the CRC matches, so its mean over frames is 1 - BLER. throughput_bps:
    payload rate of this frame, 0 when the CRC fails. csi_db, csi_phase and
    snr_per_subcarrier_db follow `USED`.
    """
    iq = np.asarray(iq, dtype=np.complex128).ravel()
    if iq.size == 0 or not np.all(np.isfinite(iq)):
        return _empty(float("nan"))
    total = float(np.mean(np.abs(iq) ** 2))
    result = _empty(total)
    last_start = iq.size - frame.samples
    if last_start < 0 or total <= EPS:
        return result
    centered = iq - np.mean(iq)  # the DC subcarrier carries no data
    found = _detect(centered, last_start)
    if found is None:
        return result
    start, cfo = found
    centered = centered * np.exp(-2j * np.pi * cfo * np.arange(iq.size))

    channel, noise = _estimate_channel(centered, start)
    first = start + PREAMBLE_LEN + N_CP
    grid = np.array([_spectrum(centered, first + s * SYMBOL) for s in range(frame.symbols)])
    phase = _track(grid, channel, frame.pilots)
    grid = grid * np.exp(-1j * phase)

    error = grid - channel * frame.grid
    wanted = np.abs(channel) ** 2
    noise_k = np.mean(np.abs(error) ** 2, axis=0)
    snr = float(wanted.mean() / max(noise_k.mean(), EPS))
    # The receiver itself only uses the preamble noise estimate.
    data_channel = channel[_DATA_IN_USED]
    equalized = grid[:, _DATA_IN_USED] / np.where(np.abs(data_channel) > EPS, data_channel, EPS)
    variance = noise / np.maximum(np.abs(data_channel) ** 2, EPS)
    llr = soft_bits(
        equalized.ravel(), frame.modulation, np.tile(variance, frame.symbols)
    )
    hard = (llr < 0).astype(np.int8)
    restored = np.empty_like(llr)
    restored[frame.permutation] = llr
    decoded = fec.decode(restored[: fec.coded_length(frame.message.size)])
    ok = fec.check_crc(decoded)
    duration = frame.samples / sample_rate_hz
    tone = float(np.polyfit(np.arange(phase.shape[0]), phase.mean(axis=1), 1)[0]) if phase.shape[0] > 1 else 0.0
    result.update(
        noise_power=total / (1 + snr),
        noise_db=float(10 * np.log10(total / (1 + snr) + EPS)),
        snr_db=float(10 * np.log10(max(snr, EPS))),
        ber=float(np.mean(hard != frame.transmitted_bits)),
        ber_coded=float(np.mean(decoded[: frame.data_bits] != frame.message[: frame.data_bits])),
        frame_ok=float(ok),
        throughput_bps=frame.data_bits / duration if ok else 0.0,
        cfo_hz=float((cfo + tone / (2 * np.pi * SYMBOL)) * sample_rate_hz),
        csi_db=(10 * np.log10(wanted + EPS)).round(2).tolist(),
        csi_phase=np.unwrap(np.angle(channel)).round(3).tolist(),
        snr_per_subcarrier_db=(
            10 * np.log10(np.maximum(wanted, EPS) / np.maximum(noise_k, EPS))
        ).round(2).tolist(),
    )
    return result
