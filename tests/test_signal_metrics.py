"""Synthetic-signal regressions; these tests never open SDR hardware."""
import unittest
from unittest.mock import Mock
import numpy as np
from pluto_monitor.dsp.sinewave import compute_sinewave_detailed_metrics
from pluto_monitor.dsp.quality import decision_directed_metrics
from pluto_monitor.dsp.bpsk import build_bpsk_tx_waveform, compute_bpsk_detailed_metrics
from pluto_monitor.dsp.qpsk import build_qpsk_tx_waveform, compute_qpsk_detailed_metrics
from pluto_monitor.dsp.qam16 import build_qam16_tx_waveform, compute_qam16_detailed_metrics
from pluto_monitor.hardware.transmitter import PlutoTransmitter, TransmitterConfig


class SignalMetricsTest(unittest.TestCase):
    def test_tx_dac_codes_preserve_all_modulations(self):
        tx = PlutoTransmitter(TransmitterConfig("unused", 2400000000, 1000000, -12))
        tx._device = Mock()
        waves = [tx.build_tone(10000, 4096)]
        for builder in (build_bpsk_tx_waveform, build_qpsk_tx_waveform, build_qam16_tx_waveform):
            waves.append(builder(4096, 2, np.random.default_rng(42))[0])
        rms_values = []
        for wave in waves:
            tx.transmit_repeat(wave)
            sent = tx._device.tx.call_args.args[0]
            codes = sent.real.astype(np.int16) + 1j * sent.imag.astype(np.int16)
            # Shaped BPSK legitimately has zero crossings. Check waveform
            # fidelity after DAC quantization, rather than forbidding zeros.
            ideal = wave / np.sqrt(np.mean(np.abs(wave) ** 2))
            recovered = codes / np.sqrt(np.mean(np.abs(codes) ** 2))
            self.assertLess(np.mean(np.abs(ideal - recovered) ** 2), 1e-6)
            self.assertGreater(np.count_nonzero(codes) / codes.size, 0.5)
            self.assertLessEqual(np.max(np.abs(codes)), 2 ** 14 + 1)
            rms_values.append(np.sqrt(np.mean(np.abs(codes) ** 2)))
        self.assertLess(20 * np.log10(max(rms_values) / min(rms_values)), 0.5)


    def test_tx_rejects_invalid_samples(self):
        tx = PlutoTransmitter(TransmitterConfig("unused", 2400000000, 1000000, -12))
        tx._device = Mock()
        for bad in (np.array([]), np.zeros(20), np.array([np.nan + 1j])):
            with self.assertRaises(ValueError):
                tx.transmit_repeat(bad)
        tx._device.tx.assert_not_called()


    def test_sinewave_known_snr_and_frequency_offset(self):
        rng = np.random.default_rng(42)
        n = np.arange(4096)
        tone = 100 * np.exp(2j * np.pi * 10870 * n / 1000000)
        noise = (rng.normal(size=n.size) + 1j * rng.normal(size=n.size)) * np.sqrt(100 / 2)
        result = compute_sinewave_detailed_metrics(
            tone + noise + 20 + 3j, sample_rate_hz=1000000, tone_frequency_hz=10000)
        self.assertAlmostEqual(result["snr_db"], 20, delta=1)
        self.assertAlmostEqual(result["tone_frequency_hz"], 10870, delta=5)
        self.assertAlmostEqual(result["noise_power"], 100, delta=10)


    def test_noise_free_tone_is_not_classified_as_noise(self):
        n = np.arange(4096)
        result = compute_sinewave_detailed_metrics(
            np.exp(2j * np.pi * 10000 * n / 1000000),
            sample_rate_hz=1000000, tone_frequency_hz=10000)
        self.assertGreater(result["snr_db"], 80)


    def test_noise_only_has_no_tone_snr(self):
        rng = np.random.default_rng(5)
        noise = rng.normal(size=4096) + 1j * rng.normal(size=4096)
        result = compute_sinewave_detailed_metrics(
            noise, sample_rate_hz=1000000, tone_frequency_hz=10000)
        self.assertTrue(np.isnan(result["snr_db"]))
        self.assertGreater(result["noise_power"], 0)


    def test_digital_error_power_refers_to_input_units(self):
        low = decision_directed_metrics(100, 1, 0.01)
        high = decision_directed_metrics(1600, 1, 0.01)
        self.assertAlmostEqual(low["snr_db"], 20)
        self.assertAlmostEqual(high["noise_db"] - low["noise_db"], 10 * np.log10(16))
        self.assertLess(low["noise_power"], low["signal_power"])
        self.assertEqual(low["snr_db"], high["snr_db"])


    def test_digital_chains_accept_signal_and_reject_noise(self):
        for builder, processor in (
            (build_bpsk_tx_waveform, compute_bpsk_detailed_metrics),
            (build_qpsk_tx_waveform, compute_qpsk_detailed_metrics),
            (build_qam16_tx_waveform, compute_qam16_detailed_metrics),
        ):
            with self.subTest(mode=builder.__name__):
                rng = np.random.default_rng(42)
                waveform = builder(1024, 2, rng)[0]
                iq = np.tile(waveform, 3)[123:123 + 2 * len(waveform)]
                iq = iq * 100 * np.exp(0.7j)
                iq += rng.normal(size=iq.size) + 1j * rng.normal(size=iq.size)
                result = processor(iq, 1000000, 1024, 2)
                self.assertTrue(np.isfinite(result["snr_db"]))
                self.assertGreater(result["snr_db"], 10)
                self.assertLess(result["noise_power"], result["signal_power"])
                scaled = processor(iq * 4, 1000000, 1024, 2)
                self.assertAlmostEqual(result["snr_db"], scaled["snr_db"], delta=0.1)
                self.assertAlmostEqual(scaled["noise_db"] - result["noise_db"], 20 * np.log10(4), delta=0.1)
                pure_noise = rng.normal(size=iq.size) + 1j * rng.normal(size=iq.size)
                absent = processor(pure_noise, 1000000, 1024, 2)
                self.assertTrue(np.isnan(absent["snr_db"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
