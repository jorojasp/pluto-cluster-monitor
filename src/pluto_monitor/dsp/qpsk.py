from __future__ import annotations

import numpy as np
from scipy import signal

# Minimum normalized preamble correlation peak required to accept a
# detection as a real preamble (rather than a spurious peak on noise).
# Empirically, pure noise yields ~0.4; SNR>=0 dB yields >=0.87.
MIN_PREAMBLE_CORR = 0.5


def build_qpsk_preamble_long() -> np.ndarray:
    """Build a 39-symbol QPSK preamble with good autocorrelation.

    Reuses the 13-chip Barker code (the same one used for BPSK/16QAM
    preambles) mapped onto the QPSK constellation by placing each
    Barker chip on both I and Q (i.e. +1 -> 1+1j, -1 -> -1-1j), then
    normalizing to unit average power and repeating 3 times.

    This avoids the poor autocorrelation of the previous 7-symbol
    preamble derived from bit-pairing the Barker-13 sequence, which
    caused spurious correlation peaks at high SNR.
    """
    barker_bits = np.array(
        [1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 1],
        dtype=np.int8,
    )
    barker_pm1 = np.where(barker_bits == 1, 1.0, -1.0)

    preamble = (barker_pm1 + 1j * barker_pm1) / np.sqrt(2.0)
    preamble_long = np.tile(preamble, 3)

    return preamble_long.astype(np.complex64)


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
    half = num_taps // 2
    t = np.arange(-half, half + 1, dtype=np.float64) / sps

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

    preamble_long = build_qpsk_preamble_long()

    if data_bits % 2 != 0:
        raise ValueError("QPSK payload requires an even number of bits")

    tx_bits = rng.integers(0, 2, size=data_bits, dtype=np.int8)
    payload_symbols = qpsk_modulate_bits(tx_bits)

    tx_symbols = np.concatenate([preamble_long, payload_symbols]).astype(np.complex64)
    tx_waveform = pulse_shape(tx_symbols, sps=sps, span=2, beta=0.35)

    return tx_waveform.astype(np.complex64), tx_bits, tx_symbols


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


def _matched_filter(iq: np.ndarray, sps: int) -> np.ndarray:
    iq = _agc_normalize(iq)

    h = raised_cosine_filter(sps=sps, span=2, beta=0.35)
    y = signal.lfilter(h, [1.0], iq)

    group_delay = (len(h) - 1) // 2
    if group_delay < len(y):
        y = y[group_delay:]

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


def compute_qpsk_detailed_metrics(
    iq: np.ndarray,
    sample_rate_hz: int,
    data_bits: int,
    sps: int,
    eps: float = 1e-12,
) -> dict[str, float]:
    del sample_rate_hz

    if iq.size == 0:
        return {
            "signal_power": float("nan"),
            "noise_power": float("nan"),
            "power_db": float("nan"),
            "noise_db": float("nan"),
            "snr_db": float("nan"),
        }

    signal_power = float(np.mean(np.abs(iq) ** 2))
    power_db = float(10.0 * np.log10(signal_power + eps))

    preamble_long = build_qpsk_preamble_long()
    rep_len = 13

    symbol_seq = _best_symbol_sequence(iq, sps=sps, preamble_long=preamble_long)
    if len(symbol_seq) < len(preamble_long) + 8:
        return {
            "signal_power": signal_power,
            "noise_power": float("nan"),
            "power_db": power_db,
            "noise_db": float("nan"),
            "snr_db": float("nan"),
        }

    corr = np.abs(signal.correlate(symbol_seq, preamble_long.conj(), mode="valid"))
    if corr.size == 0:
        return {
            "signal_power": signal_power,
            "noise_power": float("nan"),
            "power_db": power_db,
            "noise_db": float("nan"),
            "snr_db": float("nan"),
        }

    peak_idx = int(np.argmax(corr))
    peak_val = float(corr[peak_idx])

    preamble_energy = float(np.vdot(preamble_long, preamble_long).real)
    seq_power = float(np.mean(np.abs(symbol_seq) ** 2))
    norm_denom = np.sqrt(preamble_energy * len(preamble_long) * seq_power)
    norm_peak = peak_val / norm_denom if norm_denom > eps else 0.0

    if norm_peak < MIN_PREAMBLE_CORR:
        return {
            "signal_power": signal_power,
            "noise_power": float("nan"),
            "power_db": power_db,
            "noise_db": float("nan"),
            "snr_db": float("nan"),
        }

    pre_start = peak_idx
    pre_end = pre_start + len(preamble_long)

    if pre_end > len(symbol_seq):
        return {
            "signal_power": signal_power,
            "noise_power": float("nan"),
            "power_db": power_db,
            "noise_db": float("nan"),
            "snr_db": float("nan"),
        }

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
        return {
            "signal_power": signal_power,
            "noise_power": float("nan"),
            "power_db": power_db,
            "noise_db": float("nan"),
            "snr_db": float("nan"),
        }

    a = np.vdot(preamble_long, rx_preamble) / denom
    if abs(a) < 1e-6:
        a = 1.0 + 0j

    data_start = pre_end
    max_symbols = len(symbol_seq) - data_start
    max_payload_symbols = data_bits // 2
    ndata = min(int(max_payload_symbols), int(max_symbols))

    if ndata <= 0:
        return {
            "signal_power": signal_power,
            "noise_power": float("nan"),
            "power_db": power_db,
            "noise_db": float("nan"),
            "snr_db": float("nan"),
        }

    data_symbols = symbol_seq[data_start:data_start + ndata]
    data_corrected = data_symbols / a

    _, ref_symbols = qpsk_demodulate_symbols(data_corrected)
    noise_err = data_corrected - ref_symbols

    ref_power = float(np.mean(np.abs(ref_symbols) ** 2))
    noise_power = float(np.mean(np.abs(noise_err) ** 2))

    if ref_power <= 0 or noise_power <= 0:
        return {
            "signal_power": signal_power,
            "noise_power": noise_power,
            "power_db": power_db,
            "noise_db": float("nan"),
            "snr_db": float("nan"),
        }

    noise_db = float(10.0 * np.log10(noise_power + eps))
    snr_db = float(10.0 * np.log10(ref_power / (noise_power + eps)))

    return {
        "signal_power": signal_power,
        "noise_power": noise_power,
        "power_db": power_db,
        "noise_db": noise_db,
        "snr_db": snr_db,
    }


def compute_qpsk_metrics(
    iq: np.ndarray,
    sample_rate_hz: int,
    data_bits: int,
    sps: int,
    eps: float = 1e-12,
) -> tuple[float, float]:
    metrics = compute_qpsk_detailed_metrics(
        iq=iq,
        sample_rate_hz=sample_rate_hz,
        data_bits=data_bits,
        sps=sps,
        eps=eps,
    )
    return metrics["power_db"], metrics["snr_db"]