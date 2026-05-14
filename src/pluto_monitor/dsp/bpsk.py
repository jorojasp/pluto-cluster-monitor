from __future__ import annotations

import numpy as np
from scipy import signal


def build_barker_code_13() -> np.ndarray:
    barker_bits = np.array(
        [1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 1],
        dtype=np.int8,
    )
    barker_symbols = np.where(barker_bits == 1, 1.0, -1.0)
    return barker_symbols.astype(np.complex64)


def bpsk_modulate_bits(bits: np.ndarray) -> np.ndarray:
    bits = np.asarray(bits).astype(np.int8)
    symbols = np.where(bits == 1, 1.0, -1.0)
    return symbols.astype(np.complex64)


def raised_cosine_filter(sps: int, span: int = 2, beta: float = 0.35) -> np.ndarray:
    num_taps = span * sps * 2 + 1
    t = np.arange(-num_taps // 2, num_taps // 2 + 1, dtype=np.float64) / sps

    h = np.zeros_like(t)

    for i, ti in enumerate(t):
        if abs(ti) < 1e-12:
            h[i] = 1.0 + beta * (4 / np.pi - 1)
        elif beta > 0 and abs(abs(4 * beta * ti) - 1.0) < 1e-12:
            h[i] = (
                beta
                / np.sqrt(2)
                * (
                    (1 + 2 / np.pi) * np.sin(np.pi / (4 * beta))
                    + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta))
                )
            )
        else:
            numerator = (
                np.sin(np.pi * ti * (1 - beta))
                + 4 * beta * ti * np.cos(np.pi * ti * (1 + beta))
            )
            denominator = np.pi * ti * (1 - (4 * beta * ti) ** 2)
            h[i] = numerator / denominator

    h = h / np.sqrt(np.sum(h**2))
    return h.astype(np.float32)


def pulse_shape(symbols: np.ndarray, sps: int, span: int = 2, beta: float = 0.35) -> np.ndarray:
    symbols = np.asarray(symbols, dtype=np.complex64)

    upsampled = np.zeros(len(symbols) * sps, dtype=np.complex64)
    upsampled[::sps] = symbols

    h = raised_cosine_filter(sps=sps, span=span, beta=beta)
    shaped = signal.lfilter(h, [1.0], upsampled)

    return shaped.astype(np.complex64)


def build_bpsk_tx_waveform(
    data_bits: int,
    sps: int,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if rng is None:
        rng = np.random.default_rng()

    preamble = build_barker_code_13()
    preamble_long = np.tile(preamble, 3)

    tx_bits = rng.integers(0, 2, size=data_bits, dtype=np.int8)
    payload_symbols = bpsk_modulate_bits(tx_bits)

    tx_symbols = np.concatenate([preamble_long, payload_symbols]).astype(np.complex64)
    tx_waveform = pulse_shape(tx_symbols, sps=sps, span=2, beta=0.35)

    rms = np.sqrt(np.mean(np.abs(tx_waveform) ** 2))
    if rms > 0:
        tx_waveform = tx_waveform / rms

    return tx_waveform.astype(np.complex64), tx_bits, tx_symbols


def _matched_filter(iq: np.ndarray, sps: int) -> np.ndarray:
    iq = _agc_normalize(iq)

    h = raised_cosine_filter(sps=sps, span=2, beta=0.35)
    y = signal.lfilter(h, [1.0], iq)

    group_delay = (len(h) - 1) // 2
    if group_delay < len(y):
        y = y[group_delay:]

    return y.astype(np.complex64)

def _agc_normalize(iq: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    iq = np.asarray(iq, dtype=np.complex64)
    p = np.mean(np.abs(iq) ** 2)
    if p <= eps:
        return iq
    return (iq / np.sqrt(p + eps)).astype(np.complex64)


def _estimate_symbol_phase_drift(
    rx_preamble: np.ndarray,
    rep_len: int,
    eps: float = 1e-12,
) -> float:
    if len(rx_preamble) < 3 * rep_len:
        return 0.0

    rep1 = rx_preamble[0:rep_len]
    rep2 = rx_preamble[rep_len:2 * rep_len]
    rep3 = rx_preamble[2 * rep_len:3 * rep_len]

    c12 = np.vdot(rep1, rep2)
    c23 = np.vdot(rep2, rep3)

    if abs(c12) < eps or abs(c23) < eps:
        return 0.0

    phi12 = np.angle(c12)
    phi23 = np.angle(c23)

    avg_rep_phase = 0.5 * (phi12 + phi23)
    phase_per_symbol = avg_rep_phase / rep_len

    return float(phase_per_symbol)


def _apply_symbol_phase_drift_correction(
    symbols: np.ndarray,
    phase_per_symbol: float,
    reference_index: int = 0,
) -> np.ndarray:
    n = np.arange(len(symbols), dtype=np.float64) - float(reference_index)
    rot = np.exp(-1j * phase_per_symbol * n)
    return (symbols * rot).astype(np.complex64)


def _preamble_error_metric(
    rx_preamble: np.ndarray,
    ref_preamble: np.ndarray,
    h_est: complex,
    eps: float = 1e-12,
) -> float:
    corrected = rx_preamble / h_est
    err = corrected - ref_preamble
    ref_power = float(np.mean(np.abs(ref_preamble) ** 2))
    err_power = float(np.mean(np.abs(err) ** 2))
    if ref_power <= eps:
        return float("inf")
    return err_power / ref_power


def _best_symbol_sequence(
    iq: np.ndarray,
    sps: int,
    preamble_long: np.ndarray,
) -> np.ndarray:
    mf = _matched_filter(iq, sps=sps)

    best_corr = -np.inf
    best_seq = np.array([], dtype=np.complex64)

    for offset in range(sps):
        seq = mf[offset::sps]
        if len(seq) < len(preamble_long):
            continue

        corr = np.abs(signal.correlate(seq, preamble_long.conj(), mode="valid"))
        if corr.size == 0:
            continue

        peak = float(np.max(corr))
        if peak > best_corr:
            best_corr = peak
            best_seq = seq

    return best_seq.astype(np.complex64)


def compute_bpsk_metrics(
    iq: np.ndarray,
    sample_rate_hz: int,
    data_bits: int,
    sps: int,
    eps: float = 1e-12,
) -> tuple[float, float]:
    del sample_rate_hz

    if iq.size == 0:
        return float("nan"), float("nan")

    signal_power = float(np.mean(np.abs(iq) ** 2))
    power_db = float(10.0 * np.log10(signal_power + eps))

    preamble = build_barker_code_13()
    preamble_long = np.tile(preamble, 3)
    rep_len = len(preamble)

    symbol_seq = _best_symbol_sequence(iq, sps=sps, preamble_long=preamble_long)
    if len(symbol_seq) < len(preamble_long) + 8:
        return power_db, float("nan")

    corr = np.abs(signal.correlate(symbol_seq, preamble_long.conj(), mode="valid"))
    if corr.size == 0:
        return power_db, float("nan")

    peak_idx = int(np.argmax(corr))
    pre_start = peak_idx
    pre_end = pre_start + len(preamble_long)

    if pre_end > len(symbol_seq):
        return power_db, float("nan")

    rx_preamble = symbol_seq[pre_start:pre_end]

    phase_per_symbol = _estimate_symbol_phase_drift(rx_preamble, rep_len=rep_len)

    symbol_seq = _apply_symbol_phase_drift_correction(
        symbol_seq,
        phase_per_symbol=phase_per_symbol,
        reference_index=pre_start,
    )

    rx_preamble = symbol_seq[pre_start:pre_end]

    denom = np.vdot(preamble_long, preamble_long)
    if abs(denom) < eps:
        return power_db, float("nan")

    a = np.vdot(preamble_long, rx_preamble) / denom
    if abs(a) < 1e-6:
        a = 1.0 + 0j

    preamble_err_ratio = _preamble_error_metric(
        rx_preamble=rx_preamble,
        ref_preamble=preamble_long,
        h_est=a,
    )

    if preamble_err_ratio > 2.0:
        return power_db, float("nan")

    data_start = pre_end
    max_symbols = len(symbol_seq) - data_start
    ndata = min(int(data_bits), int(max_symbols))

    if ndata <= 0:
        return power_db, float("nan")

    data_symbols = symbol_seq[data_start:data_start + ndata]
    data_corrected = data_symbols / a

    decisions = np.sign(np.real(data_corrected)).astype(np.float32)
    decisions[decisions == 0] = 1.0
    decisions = decisions.astype(np.complex64)

    ref_power = float(np.mean(np.abs(decisions) ** 2))
    noise_err = data_corrected - decisions
    noise_power = float(np.mean(np.abs(noise_err) ** 2))

    if ref_power <= 0 or noise_power <= 0:
        return power_db, float("nan")

    snr_db = float(10.0 * np.log10(ref_power / (noise_power + eps)))
    return power_db, snr_db