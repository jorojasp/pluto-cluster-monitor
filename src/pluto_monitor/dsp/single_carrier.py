"""Single-carrier BPSK, QPSK and 16QAM: waveform generation and analysis.

The payload is a fixed pseudo-random sequence known to both ends, so the
receiver can measure BER and a data-aided SNR. Transmitter and receivers must
therefore run the same version of this module.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import fft, signal

RRC_BETA = 0.35
RRC_SPAN = 8  # symbols on each side of the pulse center
PAYLOAD_SEED = 20261124
# Pure noise stays well below this normalized correlation; see the tests.
MIN_PREAMBLE_CORR = 0.65
MAX_CFO_HZ = 40_000.0
PILOT_EVERY = 32  # payload symbols between pilot groups
PILOT_LEN = 4
EPS = 1e-12

_BARKER13 = np.array([1, 1, 1, 1, 1, -1, -1, 1, 1, -1, 1, -1, 1], dtype=np.float64)
PREAMBLE = np.tile(_BARKER13, 3).astype(np.complex128)


@dataclass(frozen=True, eq=False)
class Modulation:
    """A Gray-mapped constellation indexed by the integer value of its bits."""

    name: str
    bits_per_symbol: int
    constellation: np.ndarray

    def modulate(self, bits: np.ndarray) -> np.ndarray:
        bits = np.asarray(bits, dtype=np.int64).ravel()
        if bits.size % self.bits_per_symbol:
            raise ValueError(
                f"{self.name} needs a number of bits divisible by {self.bits_per_symbol}"
            )
        weights = 1 << np.arange(self.bits_per_symbol)[::-1]
        return self.constellation[bits.reshape(-1, self.bits_per_symbol) @ weights]

    def decide(self, symbols: np.ndarray) -> np.ndarray:
        """Nearest constellation index of each symbol."""
        return np.argmin(np.abs(symbols[:, None] - self.constellation[None, :]), axis=1)

    def demodulate(self, symbols: np.ndarray) -> np.ndarray:
        shifts = np.arange(self.bits_per_symbol)[::-1]
        return ((self.decide(symbols)[:, None] >> shifts) & 1).astype(np.int8).ravel()


def _qam16_constellation() -> np.ndarray:
    level = {0: -3, 1: -1, 3: 1, 2: 3}
    points = [complex(level[i >> 2], level[i & 3]) for i in range(16)]
    return np.array(points) / np.sqrt(10)


BPSK = Modulation("BPSK", 1, np.array([-1, 1], dtype=np.complex128))
QPSK = Modulation("QPSK", 2, np.array([-1 - 1j, -1 + 1j, 1 - 1j, 1 + 1j]) / np.sqrt(2))
QAM16 = Modulation("16QAM", 4, _qam16_constellation())


def rrc_filter(sps: int, span: int = RRC_SPAN, beta: float = RRC_BETA) -> np.ndarray:
    """Unit-energy root-raised-cosine taps."""
    t = np.arange(-span * sps, span * sps + 1) / sps
    h = np.empty_like(t)
    center = np.abs(t) < 1e-12
    edge = np.abs(np.abs(4 * beta * t) - 1) < 1e-12
    rest = ~(center | edge)
    h[center] = 1 + beta * (4 / np.pi - 1)
    h[edge] = beta / np.sqrt(2) * (
        (1 + 2 / np.pi) * np.sin(np.pi / (4 * beta))
        + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta))
    )
    tr = t[rest]
    h[rest] = (
        np.sin(np.pi * tr * (1 - beta)) + 4 * beta * tr * np.cos(np.pi * tr * (1 + beta))
    ) / (np.pi * tr * (1 - (4 * beta * tr) ** 2))
    return h / np.sqrt(np.sum(h**2))


def payload_bits(data_bits: int) -> np.ndarray:
    return np.random.default_rng(PAYLOAD_SEED).integers(0, 2, size=data_bits, dtype=np.int8)


def _frame_layout(payload_symbols: int) -> tuple[np.ndarray, np.ndarray]:
    """Positions of payload and pilot symbols after the preamble.

    Each pilot group follows up to PILOT_EVERY payload symbols. Pilots allow
    phase tracking without symbol decisions, which slip at low SNR.
    """
    groups = -(-payload_symbols // PILOT_EVERY)
    total = payload_symbols + groups * PILOT_LEN
    is_pilot = np.zeros(total, dtype=bool)
    for g in range(groups):
        end = min((g + 1) * PILOT_EVERY, payload_symbols) + g * PILOT_LEN
        is_pilot[end : end + PILOT_LEN] = True
    return np.flatnonzero(~is_pilot), np.flatnonzero(is_pilot)


def _pilots(count: int) -> np.ndarray:
    return 1.0 - 2.0 * np.random.default_rng(PAYLOAD_SEED + 1).integers(0, 2, size=count)


def frame_samples(mod: Modulation, data_bits: int, sps: int) -> int:
    if data_bits % mod.bits_per_symbol:
        raise ValueError(
            f"data_bits must be divisible by {mod.bits_per_symbol} for {mod.name}"
        )
    payload = data_bits // mod.bits_per_symbol
    pilots = -(-payload // PILOT_EVERY) * PILOT_LEN
    return (PREAMBLE.size + payload + pilots) * sps


def frame_symbols(mod: Modulation, data_bits: int) -> np.ndarray:
    payload = mod.modulate(payload_bits(data_bits))
    data_pos, pilot_pos = _frame_layout(payload.size)
    body = np.empty(data_pos.size + pilot_pos.size, dtype=np.complex128)
    body[data_pos] = payload
    body[pilot_pos] = _pilots(pilot_pos.size)
    return np.concatenate([PREAMBLE, body])


def build_waveform(
    mod: Modulation, data_bits: int, sps: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (waveform, payload bits, frame symbols).

    Shaping is circular because the radio repeats the buffer without gaps.
    """
    frame_samples(mod, data_bits, sps)
    symbols = frame_symbols(mod, data_bits)
    upsampled = np.zeros(symbols.size * sps, dtype=np.complex128)
    upsampled[::sps] = symbols
    taps = rrc_filter(sps)
    half = taps.size // 2
    padded = np.take(upsampled, np.arange(-half, upsampled.size + half), mode="wrap")
    waveform = np.convolve(padded, taps, mode="valid")
    return waveform.astype(np.complex64), payload_bits(data_bits), symbols


def _detect(
    filtered: np.ndarray, sps: int, sample_rate_hz: float, last_start: int
) -> tuple[int, float, float]:
    """Search preamble start (samples) and coarse CFO. Returns (start, cfo, corr)."""
    template = np.zeros((PREAMBLE.size - 1) * sps + 1, dtype=np.complex64)
    template[::sps] = PREAMBLE
    mask = np.zeros(template.size)
    mask[::sps] = 1.0
    energy = signal.fftconvolve(np.abs(filtered) ** 2, mask[::-1], mode="valid")
    norm = np.sqrt(np.maximum(energy, EPS) * PREAMBLE.size)[: last_start + 1]

    # Half the preamble's frequency resolution keeps the mismatch loss small.
    # Offsets are whole FFT bins so each hypothesis is a spectrum shift.
    nfft = fft.next_fast_len(filtered.size + template.size - 1)
    bin_hz = sample_rate_hz / nfft
    step = max(1, round(sample_rate_hz / (2 * PREAMBLE.size * sps) / bin_hz))
    limit = min(MAX_CFO_HZ, 0.1 * sample_rate_hz / sps)
    steps = int(np.ceil(limit / (step * bin_hz)))
    spectrum = fft.fft(filtered.astype(np.complex64), nfft)
    reference = np.conj(fft.fft(template, nfft))
    best = (0, 0.0, 0.0)
    for k in range(-steps, steps + 1):
        corr = fft.ifft(spectrum * np.roll(reference, k * step))
        metric = np.abs(corr[: norm.size]) / norm
        peak = int(np.argmax(metric))
        if metric[peak] > best[2]:
            best = (peak, k * step * bin_hz, float(metric[peak]))
    return best


def _delay_samples(x: np.ndarray, start: int, count: int, sps: int, frac: float) -> np.ndarray:
    """Symbol-spaced samples at start + frac + k*sps using windowed-sinc interpolation."""
    half = 8
    offsets = np.arange(-half, half + 1)
    arg = frac - offsets
    taps = np.sinc(arg) * np.cos(np.pi * arg / (2 * (half + 1))) ** 2
    idx = start + np.arange(count)[:, None] * sps + offsets[None, :]
    inside = (idx >= 0) & (idx < x.size)
    return np.where(inside, x[np.clip(idx, 0, x.size - 1)], 0) @ taps


def _fine_cfo(preamble_rx: np.ndarray) -> float:
    """Residual phase advance per symbol over the preamble (radians)."""
    z = preamble_rx * np.conj(PREAMBLE)
    size = 4096
    spectrum = np.abs(np.fft.fft(z, size))
    k = int(np.argmax(spectrum))
    a, b, c = spectrum[k - 1], spectrum[k], spectrum[(k + 1) % size]
    curvature = a - 2 * b + c
    delta = 0.5 * (a - c) / curvature if abs(curvature) > EPS else 0.0
    return float(np.angle(np.exp(2j * np.pi * (k + delta) / size)))


def _pilot_phase(preamble: np.ndarray, body: np.ndarray, pilot_pos: np.ndarray) -> np.ndarray:
    """Phase of every body symbol, interpolated between known symbol groups."""
    z = preamble * np.conj(PREAMBLE)
    centers = [6.0 - PREAMBLE.size, 19.0 - PREAMBLE.size, 32.0 - PREAMBLE.size]
    sums = list(z.reshape(3, 13).sum(axis=1))
    pilots = (body[pilot_pos] * _pilots(pilot_pos.size)).reshape(-1, PILOT_LEN)
    centers += list(pilot_pos.reshape(-1, PILOT_LEN).mean(axis=1))
    sums += list(pilots.sum(axis=1))
    x = np.array(centers)
    phase = np.unwrap(np.angle(np.array(sums)))
    # A local line over neighboring groups averages noise without lagging a
    # constant frequency offset.
    smooth = np.empty_like(phase)
    for i in range(phase.size):
        lo, hi = max(0, i - 3), min(phase.size, i + 4)
        smooth[i] = np.polyval(np.polyfit(x[lo:hi] - x[i], phase[lo:hi], 1), 0.0)
    return np.interp(np.arange(body.size), x, smooth)


def _dc_offset(iq: np.ndarray, start: int, frac: float, cfo: float, sample_rate_hz: float,
               waveform: np.ndarray) -> complex:
    """Mean of the received frame that the known frame does not explain."""
    n = np.arange(waveform.size)
    ramp = np.exp(-2j * np.pi * np.fft.fftfreq(n.size) * frac)
    model = np.fft.ifft(np.fft.fft(waveform) * ramp)
    model = model * np.exp(2j * np.pi * cfo / sample_rate_hz * (n + start))
    frame = iq[start : start + n.size]
    columns = np.stack([model, np.ones(n.size)], axis=1)
    return complex(np.linalg.lstsq(columns, frame, rcond=None)[0][1])


def _empty_metrics(total_power: float) -> dict[str, float]:
    nan = float("nan")
    return {
        "signal_power": total_power,
        "power_db": float(10 * np.log10(total_power + EPS)) if np.isfinite(total_power) else nan,
        "noise_power": nan,
        "noise_db": nan,
        "snr_db": nan,
        "ber": nan,
        "cfo_hz": nan,
    }


def analyze(
    mod: Modulation, iq: np.ndarray, sample_rate_hz: float, data_bits: int, sps: int
) -> dict[str, float]:
    """Synchronize one full frame and return power, SNR, BER and CFO.

    SNR compares the recovered symbols with the known payload after a single
    complex gain, so it includes thermal noise, distortion and residual
    synchronization error. Estimated noise is referred to total IQ power:
    P_noise = P_total / (1 + SNR). Values are NaN when no frame is found.
    """
    iq = np.asarray(iq, dtype=np.complex128).ravel()
    if iq.size == 0 or not np.all(np.isfinite(iq)):
        return _empty_metrics(float("nan"))
    total = float(np.mean(np.abs(iq) ** 2))
    result = _empty_metrics(total)
    length = frame_samples(mod, data_bits, sps)
    last_start = iq.size - length
    if last_start < 0 or total <= EPS:
        return result

    taps = rrc_filter(sps)
    centered = iq - np.mean(iq)
    start, cfo, corr = _detect(
        signal.fftconvolve(centered, taps, mode="same"), sps, sample_rate_hz, last_start
    )
    if corr < MIN_PREAMBLE_CORR:
        return result

    n = np.arange(iq.size)

    def matched(offset_hz: float) -> np.ndarray:
        rotated = centered * np.exp(-2j * np.pi * offset_hz / sample_rate_hz * n)
        return signal.fftconvolve(rotated, taps, mode="same")

    # Each pass refines timing, frequency and DC with the previous estimates.
    waveform = build_waveform(mod, data_bits, sps)[0]
    fractions = np.linspace(-1, 1, 33)
    for _ in range(2):
        filtered = matched(cfo)
        scores = [
            abs(np.vdot(PREAMBLE, _delay_samples(filtered, start, PREAMBLE.size, sps, f)))
            for f in fractions
        ]
        frac = float(fractions[int(np.argmax(scores))])
        step = _fine_cfo(_delay_samples(filtered, start, PREAMBLE.size, sps, frac))
        cfo += step * sample_rate_hz / (2 * np.pi * sps)
        centered = iq - _dc_offset(iq, start, frac, cfo, sample_rate_hz, waveform)

    symbols = _delay_samples(matched(cfo), start, length // sps, sps, frac)
    preamble, body = symbols[: PREAMBLE.size], symbols[PREAMBLE.size :]
    data_pos, pilot_pos = _frame_layout(data_bits // mod.bits_per_symbol)
    phase = _pilot_phase(preamble, body, pilot_pos)
    derotated = body * np.exp(-1j * phase)
    # Amplitude comes from the pilots only: BER must not use the payload.
    amplitude = float(np.mean((derotated[pilot_pos] * _pilots(pilot_pos.size)).real))
    if amplitude <= EPS:
        return result
    payload = derotated[data_pos] / amplitude
    bits = payload_bits(data_bits)
    reference = mod.modulate(bits)
    scale = np.vdot(reference, payload) / np.vdot(reference, reference)
    error = float(np.mean(np.abs(payload - scale * reference) ** 2))
    wanted = float(np.abs(scale) ** 2 * np.mean(np.abs(reference) ** 2))
    noise = total * error / max(wanted + error, EPS)
    residual = float(np.polyfit(np.arange(phase.size), phase, 1)[0])
    result.update(
        noise_power=noise,
        noise_db=float(10 * np.log10(noise + EPS)),
        snr_db=float(10 * np.log10(max(wanted, EPS) / max(error, EPS))),
        ber=float(np.mean(mod.demodulate(payload) != bits)),
        cfo_hz=float(cfo + residual * sample_rate_hz / (2 * np.pi * sps)),
    )
    return result
