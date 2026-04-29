from __future__ import annotations

import numpy as np
from scipy import signal


def build_qpsk_barker_bits() -> np.ndarray:
    bits = np.array(
        [1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 1],
        dtype=np.int8,
    )

    if len(bits) % 2 != 0:
        bits = np.concatenate([bits, np.zeros(1, dtype=np.int8)])

    return bits.astype(np.int8)


def qpsk_modulate_bits(bits: np.ndarray) -> np.ndarray:
    bits = np.asarray(bits).astype(np.int8).flatten()

    if len(bits) % 2 != 0:
        raise ValueError("QPSK modulation requires an even number of bits")

    bit_pairs = bits.reshape(-1, 2)

    symbol_idx = bit_pairs[:, 0] * 2 + bit_pairs[:, 1]

    phase = np.pi / 4.0 + symbol_idx * (np.pi / 2.0)
    symbols = np.exp(1j * phase)

    return symbols.astype(np.complex64)


def qpsk_demodulate_symbols(symbols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    symbols = np.asarray(symbols, dtype=np.complex64)

    angles = np.angle(symbols)
    angles = (angles - np.pi / 4.0) % (2.0 * np.pi)

    symbol_idx = np.round(angles / (np.pi / 2.0)) % 4
    symbol_idx = symbol_idx.astype(np.int8)

    ref_phase = np.pi / 4.0 + symbol_idx * (np.pi / 2.0)
    ref_symbols = np.exp(1j * ref_phase).astype(np.complex64)

    return symbol_idx, ref_symbols


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


def build_qpsk_tx_waveform(
    data_bits: int,
    sps: int,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if rng is None:
        rng = np.random.default_rng()

    preamble_bits = build_qpsk_barker_bits()
    preamble_symbols = qpsk_modulate_bits(preamble_bits)
    preamble_long = np.tile(preamble_symbols, 3)

    if data_bits % 2 != 0:
        raise ValueError("QPSK payload requires an even number of bits")

    tx_bits = rng.integers(0, 2, size=data_bits, dtype=np.int8)
    payload_symbols = qpsk_modulate_bits(tx_bits)

    tx_symbols = np.concatenate([preamble_long, payload_symbols]).astype(np.complex64)
    tx_waveform = pulse_shape(tx_symbols, sps=sps, span=2, beta=0.35)

    rms = np.sqrt(np.mean(np.abs(tx_waveform) ** 2))
    if rms > 0:
        tx_waveform = tx_waveform / rms

    return tx_waveform.astype(np.complex64), tx_bits, tx_symbols


def _matched_filter(iq: np.ndarray, sps: int) -> np.ndarray:
    h = raised_cosine_filter(sps=sps, span=2, beta=0.35)
    y = signal.lfilter(h, [1.0], iq)
    return y.astype(np.complex64)


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


def compute_qpsk_metrics(
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

    preamble_bits = build_qpsk_barker_bits()
    preamble_symbols = qpsk_modulate_bits(preamble_bits)
    preamble_long = np.tile(preamble_symbols, 3)

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

    denom = np.vdot(preamble_long, preamble_long)
    if abs(denom) < eps:
        return power_db, float("nan")

    a = np.vdot(preamble_long, rx_preamble) / denom
    if abs(a) < 1e-6:
        a = 1.0 + 0j

    data_start = pre_end
    max_symbols = len(symbol_seq) - data_start
    max_payload_symbols = data_bits // 2
    ndata = min(int(max_payload_symbols), int(max_symbols))

    if ndata <= 0:
        return power_db, float("nan")

    data_symbols = symbol_seq[data_start:data_start + ndata]
    data_corrected = data_symbols / a

    _, ref_symbols = qpsk_demodulate_symbols(data_corrected)
    noise_err = data_corrected - ref_symbols

    ref_power = float(np.mean(np.abs(ref_symbols) ** 2))
    noise_power = float(np.mean(np.abs(noise_err) ** 2))

    if ref_power <= 0 or noise_power <= 0:
        return power_db, float("nan")

    snr_db = float(10.0 * np.log10(ref_power / (noise_power + eps)))
    return power_db, snr_db