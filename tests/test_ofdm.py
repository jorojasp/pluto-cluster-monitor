"""OFDM, FEC and channel tests on simulated signals only."""
from math import erfc, sqrt
from unittest.mock import Mock

import numpy as np
import pytest

from pluto_monitor.dsp import fec, ofdm
from pluto_monitor.dsp import single_carrier as sc
from pluto_monitor.dsp.channel import Channel
from pluto_monitor.dsp.modes import get_mode
from pluto_monitor.hardware.transmitter import PlutoTransmitter, TransmitterConfig

FS = 2_000_000
by_mod = pytest.mark.parametrize("mod", [sc.QPSK, sc.QAM16], ids=lambda m: m.name)


def receive(mod, rng, frames=6, bits=1024, **channel):
    frame = ofdm.OfdmFrame(mod, bits)
    wave = frame.waveform()
    return [
        ofdm.analyze(frame, Channel(**channel).receive(wave, 2 * frame.samples + 16, FS, rng), FS)
        for _ in range(frames)
    ]


def values(results, key):
    return np.array([r[key] for r in results], dtype=float)


# ---- FEC ------------------------------------------------------------------


def test_code_uses_the_standard_generators():
    pairs = fec.encode([1, 0, 0, 0, 0, 0, 0])[:14].reshape(-1, 2)
    assert "".join(map(str, pairs[:, 0])) == f"{0o133:07b}"
    assert "".join(map(str, pairs[:, 1])) == f"{0o171:07b}"


def test_viterbi_corrects_errors_and_crc_detects_them():
    rng = np.random.default_rng(1)
    message = fec.append_crc(rng.integers(0, 2, 400))
    llr = 1 - 2.0 * fec.encode(message)
    llr[::25] *= -1  # isolated errors
    assert np.array_equal(fec.decode(llr), message)
    assert fec.check_crc(message)
    message[7] ^= 1
    assert not fec.check_crc(message)


def test_coding_gain():
    rng = np.random.default_rng(2)
    errors = 0
    for _ in range(20):
        message = rng.integers(0, 2, 500)
        coded = 1 - 2.0 * fec.encode(message)
        errors += np.sum(fec.decode(coded + rng.normal(size=coded.size) / sqrt(10 ** 0.3)) != message)
    assert errors / 10_000 < 0.005  # uncoded BPSK at the same Eb/N0 (3 dB): 0.023


def test_interleaver_is_a_permutation():
    assert np.array_equal(np.sort(fec.interleaver(500)), np.arange(500))


# ---- frame ----------------------------------------------------------------


def test_frame_layout_and_power():
    frame = ofdm.OfdmFrame(sc.QPSK, 1024)
    wave = frame.waveform()
    assert wave.size == frame.samples == 320 + 80 * frame.symbols
    assert ofdm.DATA.size == 48 and ofdm.PILOTS.size == 4
    for part in (wave[:160], wave[160:320], wave[320:]):
        assert np.mean(np.abs(part) ** 2) == pytest.approx(1, rel=0.1)
    # The prefix repeats the end of each symbol, and DC is empty.
    symbol = wave[320:400]
    assert np.allclose(symbol[:16], symbol[-16:], atol=1e-5)
    assert abs(np.fft.fft(symbol[16:])[0]) < 1e-3


@by_mod
def test_clean_frame_is_error_free(mod):
    result = receive(mod, np.random.default_rng(3), frames=1, snr_db=35)[0]
    assert result["ber"] == 0 and result["ber_coded"] == 0 and result["frame_ok"] == 1
    frame = ofdm.OfdmFrame(mod, 1024)
    assert result["throughput_bps"] == pytest.approx(1024 * FS / frame.samples)
    assert len(result["csi_db"]) == len(result["snr_per_subcarrier_db"]) == 52


@by_mod
@pytest.mark.parametrize("snr_db", [5, 10, 20])
def test_reported_snr(mod, snr_db):
    # 52 of 64 bins carry the signal, and channel estimation costs under 1.5 dB.
    expected = snr_db + 10 * np.log10(64 / 52)
    median = np.median(values(receive(mod, np.random.default_rng(4), snr_db=snr_db), "snr_db"))
    assert expected - 1.5 < median < expected + 0.5


def test_raw_ber_is_close_to_theory():
    results = receive(sc.QPSK, np.random.default_rng(5), frames=20, snr_db=5)

    def theory(db):
        return 0.5 * erfc(sqrt(10 ** (db / 10) * 64 / 52 / 2))

    assert theory(5) < values(results, "ber").mean() < theory(3.5)


@by_mod
@pytest.mark.parametrize("cfo_hz", [-55_000, -9_000, 0, 31_000, 55_000])
def test_carrier_offset(mod, cfo_hz):
    results = receive(mod, np.random.default_rng(6), frames=3, snr_db=18, cfo_hz=cfo_hz)
    assert values(results, "cfo_hz") == pytest.approx(cfo_hz, abs=60)
    assert values(results, "frame_ok").all()


@by_mod
def test_fec_recovers_multipath_with_raw_errors(mod):
    snr = 11 if mod is sc.QPSK else 19
    results = receive(mod, np.random.default_rng(7), frames=8, snr_db=snr,
                      paths=((0, 1), (3.4, 0.6j), (7.2, -0.35)))
    assert values(results, "ber").mean() > 1e-3
    assert values(results, "frame_ok").all()


def test_csi_matches_the_channel():
    paths = ((0.0, 1.0), (5.0, 0.5))
    result = receive(sc.QPSK, np.random.default_rng(8), frames=1, snr_db=35, paths=paths)[0]
    expected = np.abs(sum(g * np.exp(-2j * np.pi * ofdm.USED * d / 64) for d, g in paths))
    measured = 10 ** (np.array(result["csi_db"]) / 20)
    ratio = measured / expected
    assert np.std(ratio) / np.mean(ratio) < 0.05


def test_clock_offset_and_dc_are_tolerated():
    results = receive(sc.QAM16, np.random.default_rng(9), frames=4, snr_db=25, cfo_hz=40_000,
                      clock_ppm=20, dc=120 + 50j)
    assert values(results, "frame_ok").all()


def test_low_snr_fails_the_crc_instead_of_reporting_throughput():
    results = receive(sc.QAM16, np.random.default_rng(10), snr_db=2)
    assert not values(results, "frame_ok").any()
    assert not values(results, "throughput_bps").any()


def test_noise_never_looks_like_a_frame():
    frame = ofdm.OfdmFrame(sc.QPSK, 1024)
    rng = np.random.default_rng(11)
    for _ in range(40):
        noise = rng.normal(size=5000) + 1j * rng.normal(size=5000)
        result = ofdm.analyze(frame, noise, FS)
        assert np.isnan(result["snr_db"]) and np.isnan(result["frame_ok"])


# ---- integration ----------------------------------------------------------


@pytest.mark.parametrize("name", ["OFDM-QPSK", "OFDM-16QAM"])
def test_mode_rejects_bad_payloads(name):
    rf = {"sample_rate_hz": FS, "samples_per_frame": 4096, "data_bits": 1024}
    get_mode(name).validate(rf)
    for bits in (0, 1001, 1 << 17):
        with pytest.raises(ValueError):
            get_mode(name).validate({**rf, "data_bits": bits})


def test_transmitter_never_exceeds_the_dac_range():
    tx = PlutoTransmitter(TransmitterConfig("unused", 2_482_000_000, FS, -40))
    tx._device = Mock()
    tx.transmit_repeat(ofdm.OfdmFrame(sc.QAM16, 4096).waveform())
    sent = tx._device.tx.call_args.args[0]
    assert np.abs(sent).max() <= 2 ** 14 + 1
    assert np.sqrt(np.mean(np.abs(sent) ** 2)) > 3000


def test_metrics_reach_the_dashboard_as_valid_json():
    import json

    from pluto_monitor.services.acquisition import acquire_once
    from pluto_monitor.web.service import _result_to_json

    rf = {"sample_rate_hz": FS, "samples_per_frame": 4096, "data_bits": 1024}
    frame = ofdm.OfdmFrame(sc.QPSK, 1024)
    iq = Channel(snr_db=20).receive(
        frame.waveform(), 2 * frame.samples + 16, FS, np.random.default_rng(12))
    radio = Mock()
    radio.read_samples.return_value = iq
    result = acquire_once({"A": {"radio_ids": ["u"]}}, {"u": radio}, "OFDM-QPSK", rf)
    payload = json.loads(json.dumps(_result_to_json(result, {"u": "s"}), allow_nan=False))
    entry = payload["groups"]["A"]["radios"][0]
    assert entry["frame_ok"] == 1 and len(entry["csi_db"]) == 52
