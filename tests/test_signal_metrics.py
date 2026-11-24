"""Synthetic-signal regressions; these tests never open SDR hardware."""
from unittest.mock import Mock

import numpy as np
import pytest

from pluto_monitor.dsp import single_carrier as sc
from pluto_monitor.dsp.modes import MODES, get_mode
from pluto_monitor.dsp.sinewave import build_tone, compute_sinewave_detailed_metrics
from pluto_monitor.hardware.transmitter import PlutoTransmitter, TransmitterConfig

FS = 1_000_000
RF = {"center_frequency_hz": 2_400_000_000, "sample_rate_hz": FS, "samples_per_frame": 4096,
      "rx_gain_db": 30, "tx_gain_db": -12, "sps": 2, "data_bits": 4096,
      "tone_frequency_hz": 10_000}
MODULATIONS = [sc.BPSK, sc.QPSK, sc.QAM16]
by_name = pytest.mark.parametrize("mod", MODULATIONS, ids=lambda m: m.name)


def capture(mod, rng, *, bits=4096, snr_db=20.0, cfo_hz=0.0, dc=0.0, level=100.0, fraction=None):
    """Two frames of the cyclic waveform from a random, fractional position."""
    wave = sc.build_waveform(mod, bits, 2)[0]
    size = wave.size
    spectrum = np.fft.fft(wave)
    shift = rng.integers(size) + (rng.random() if fraction is None else fraction)
    moved = np.fft.ifft(spectrum * np.exp(2j * np.pi * np.fft.fftfreq(size) * shift))
    n = np.arange(2 * size + 16)
    iq = moved[n % size] * np.exp(2j * np.pi * cfo_hz / FS * n + 1j * rng.uniform(0, 2 * np.pi))
    iq = iq * level / np.sqrt(np.mean(np.abs(iq) ** 2))
    sigma = level * 10 ** (-snr_db / 20) / np.sqrt(2)
    return iq + sigma * (rng.normal(size=n.size) + 1j * rng.normal(size=n.size)) + dc


# The matched filter gains 10*log10(sps) = 3 dB over the sample SNR.
@by_name
@pytest.mark.parametrize("snr_db", [8, 14, 20])
def test_reported_snr_matches_the_channel(mod, snr_db):
    rng = np.random.default_rng(1)
    values = [sc.analyze(mod, capture(mod, rng, snr_db=snr_db), FS, 4096, 2)["snr_db"]
              for _ in range(8)]
    assert np.median(values) == pytest.approx(snr_db + 3, abs=0.8)


@by_name
@pytest.mark.parametrize("bits", [128, 1024])
def test_short_payloads_are_not_biased(mod, bits):
    rng = np.random.default_rng(2)
    values = [sc.analyze(mod, capture(mod, rng, bits=bits), FS, bits, 2)["snr_db"]
              for _ in range(8)]
    assert np.median(values) == pytest.approx(23, abs=1.2)


@by_name
@pytest.mark.parametrize("cfo_hz", [-38_000, -8_000, 500, 19_000, 38_000])
def test_carrier_offset_is_measured_and_corrected(mod, cfo_hz):
    rng = np.random.default_rng(3)
    result = sc.analyze(mod, capture(mod, rng, cfo_hz=cfo_hz), FS, 4096, 2)
    assert result["cfo_hz"] == pytest.approx(cfo_hz, abs=20)
    assert result["snr_db"] > 21
    assert result["ber"] == 0


def test_ber_follows_theory_for_qpsk():
    rng = np.random.default_rng(4)
    bers = [sc.analyze(sc.QPSK, capture(sc.QPSK, rng, snr_db=5), FS, 4096, 2)["ber"]
            for _ in range(25)]
    # Es/N0 = 8 dB gives Q(sqrt(Es/N0)) = 6.0e-3.
    assert 3e-3 < np.mean(bers) < 1.1e-2


@by_name
def test_dc_offset_does_not_change_the_result(mod):
    rng = np.random.default_rng(5)
    result = sc.analyze(mod, capture(mod, rng, dc=80 + 40j, cfo_hz=3000), FS, 4096, 2)
    assert result["snr_db"] > 21 and result["ber"] == 0


@by_name
def test_noise_only_and_short_captures_have_no_estimate(mod):
    rng = np.random.default_rng(6)
    noise = rng.normal(size=9000) + 1j * rng.normal(size=9000)
    result = sc.analyze(mod, noise, FS, 1024, 2)
    assert np.isnan(result["snr_db"]) and np.isnan(result["ber"])
    assert np.isfinite(result["power_db"])
    short = capture(mod, rng, bits=1024)[: sc.frame_samples(mod, 1024, 2) - 1]
    assert np.isnan(sc.analyze(mod, short, FS, 1024, 2)["snr_db"])


@by_name
def test_error_power_refers_to_input_units(mod):
    iq = capture(mod, np.random.default_rng(7))
    low, high = (sc.analyze(mod, iq * k, FS, 4096, 2) for k in (1, 4))
    assert high["snr_db"] == pytest.approx(low["snr_db"], abs=0.1)
    assert high["noise_db"] - low["noise_db"] == pytest.approx(20 * np.log10(4), abs=0.1)
    assert low["noise_power"] < low["signal_power"]


@by_name
def test_gray_mapping_changes_one_bit_between_neighbors(mod):
    points = mod.constellation
    for i, point in enumerate(points):
        distance = np.abs(points - point)
        nearest = np.min(distance[distance > 1e-9])
        for j in np.flatnonzero(np.abs(distance - nearest) < 1e-9):
            assert bin(i ^ int(j)).count("1") == 1


@by_name
def test_bits_survive_modulation(mod):
    bits = sc.payload_bits(64)
    assert np.array_equal(mod.demodulate(mod.modulate(bits)), bits)
    assert np.mean(np.abs(mod.constellation) ** 2) == pytest.approx(1)


def test_payload_is_the_same_on_both_ends():
    assert np.array_equal(sc.build_waveform(sc.QPSK, 512, 2)[0], sc.build_waveform(sc.QPSK, 512, 2)[0])


# ---- mode registry --------------------------------------------------------


@pytest.mark.parametrize("name", sorted(MODES))
def test_every_mode_measures_its_own_waveform(name):
    mode = get_mode(name)
    mode.validate(RF)
    wave = mode.build_waveform(RF)
    samples = mode.capture_samples(RF)
    rng = np.random.default_rng(8)
    iq = np.resize(np.roll(wave, 321), samples) * 100
    iq = iq + rng.normal(size=samples) + 1j * rng.normal(size=samples)
    result = mode.measure(iq, RF)
    assert result["snr_db"] > 15
    assert {"signal_power", "noise_power", "power_db"} <= result.keys()


@by_name
def test_capture_always_contains_a_full_frame(mod):
    assert get_mode(mod.name).capture_samples(RF) >= 2 * sc.frame_samples(mod, 4096, 2)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="Unsupported mode"):
        get_mode("NOPE")


# ---- transmitter ----------------------------------------------------------


def _transmitter():
    tx = PlutoTransmitter(TransmitterConfig("unused", 2_400_000_000, FS, -12))
    tx._device = Mock()
    return tx


def test_tx_dac_codes_preserve_all_modes():
    tx = _transmitter()
    rms_values = []
    for mode in MODES.values():
        if mode.controls == "ofdm":
            continue  # its peaks limit the drive; see tests/test_ofdm.py
        wave = mode.build_waveform(RF)
        tx.transmit_repeat(wave)
        sent = tx._device.tx.call_args.args[0]
        codes = sent.real.astype(np.int16) + 1j * sent.imag.astype(np.int16)
        # Check waveform fidelity after quantization: shaped BPSK legitimately
        # has zero crossings.
        ideal = wave / np.sqrt(np.mean(np.abs(wave) ** 2))
        recovered = codes / np.sqrt(np.mean(np.abs(codes) ** 2))
        assert np.mean(np.abs(ideal - recovered) ** 2) < 1e-6
        assert np.max(np.abs(codes)) <= 2 ** 14 + 1
        rms_values.append(np.sqrt(np.mean(np.abs(codes) ** 2)))
    assert 20 * np.log10(max(rms_values) / min(rms_values)) < 0.5


def test_tx_rejects_invalid_samples():
    tx = _transmitter()
    for bad in (np.array([]), np.zeros(20), np.array([np.nan + 1j])):
        with pytest.raises(ValueError):
            tx.transmit_repeat(bad)
    tx._device.tx.assert_not_called()


# ---- sine wave ------------------------------------------------------------


def test_tone_repeats_without_a_phase_jump():
    tone = build_tone(10_000, FS, 4096)
    step = np.angle(tone[1] / tone[0])
    assert np.angle(tone[0] / tone[-1]) == pytest.approx(step, abs=1e-3)
    assert step * FS / (2 * np.pi) == pytest.approx(10_000, abs=FS / 4096)


def test_sinewave_known_snr_and_frequency_offset():
    rng = np.random.default_rng(42)
    n = np.arange(4096)
    tone = 100 * np.exp(2j * np.pi * 10870 * n / FS)
    noise = (rng.normal(size=n.size) + 1j * rng.normal(size=n.size)) * np.sqrt(100 / 2)
    result = compute_sinewave_detailed_metrics(
        tone + noise + 20 + 3j, sample_rate_hz=FS, tone_frequency_hz=10000)
    assert result["snr_db"] == pytest.approx(20, abs=1)
    assert result["tone_frequency_hz"] == pytest.approx(10870, abs=5)
    assert result["noise_power"] == pytest.approx(100, abs=10)


def test_noise_free_tone_is_not_classified_as_noise():
    n = np.arange(4096)
    result = compute_sinewave_detailed_metrics(
        np.exp(2j * np.pi * 10000 * n / FS), sample_rate_hz=FS, tone_frequency_hz=10000)
    assert result["snr_db"] > 80


def test_noise_only_has_no_tone_snr():
    rng = np.random.default_rng(5)
    noise = rng.normal(size=4096) + 1j * rng.normal(size=4096)
    result = compute_sinewave_detailed_metrics(noise, sample_rate_hz=FS, tone_frequency_hz=10000)
    assert np.isnan(result["snr_db"])
    assert result["noise_power"] > 0
