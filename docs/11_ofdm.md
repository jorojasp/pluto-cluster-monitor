# Coded OFDM

Implemented in `dsp/ofdm.py` (frame and receiver), `dsp/fec.py` (code and CRC) and
`dsp/channel.py` (simulated channel). Modes `OFDM-QPSK` and `OFDM-16QAM` are in the
mode registry. **Only simulated so far**; over-the-air validation is pending.

## Parameters and reasons

| Parameter | Value | Reason |
| --- | --- | --- |
| Sample rate | 2 MS/s recommended | 31.25 kHz spacing: 1% residual offset gives about -35 dB ICI |
| FFT / prefix | 64 / 16 samples | 8 us prefix at 2 MS/s, far above indoor delay spread |
| Subcarriers | 48 data, 4 pilots, null DC | 802.11 layout; the null avoids the receiver's DC offset |
| Preamble | STF 160 + LTF 160 samples | STF corrects up to +/-62.5 kHz at 2 MS/s; LTF gives timing and CSI |
| Code | Convolutional K=7, rate 1/2 (133/171), CRC-32 | Standard and simple; the CRC gives BLER and throughput |
| Payload | Fixed pseudo-random, interleaved over the frame | Known on both ends, so BER is measurable |

The layout matches the prototypes in the reference papers (48 data subcarriers),
with a 2 MHz instead of a 20 MHz bandwidth. `sps` does not apply.

## Receiver

STF autocorrelation (coarse timing and offset), LTF correlation (exact timing and
fine offset), LMMSE channel estimate, pilot tracking of phase and sample clock,
soft demapping, Viterbi and CRC. The known payload is used only to count errors and
to report SNR, never to decode.

## Metrics

| Field | Meaning |
| --- | --- |
| `ber`, `ber_coded` | Bit error rate before and after FEC |
| `frame_ok` | 1 if the CRC matches; its mean is 1 - BLER |
| `throughput_bps` | Payload rate of the frame including preamble, 0 if the CRC fails |
| `snr_db`, `snr_per_subcarrier_db` | Symbol SNR, total and per used subcarrier |
| `csi_db`, `csi_phase` | Channel on subcarriers -26..-1, 1..26 |
| `cfo_hz` | Carrier offset |

They are in the API and session logs; the dashboard table shows SNR and raw BER.
Undetected frames have no values: count them as lost when computing BLER.

## Simulation

```bash
python scripts/simulate_ofdm.py               # AWGN
python scripts/simulate_ofdm.py --multipath   # three paths
```

It writes a CSV and a plot to `data/exports/`. With 2048 bits and 60 frames per
point, all frames pass from 4 dB (QPSK) and 10 dB (16QAM) per-sample SNR in AWGN.
In AWGN the receiver is about 0.9 dB from theory. Sixty frames cannot resolve BLER
below about 5%.

## Limits

OFDM peaks (9-10 dB PAPR) make the transmitter reduce its average drive by about
3-4 dB compared with the other modes. Decoding time grows with `data_bits`
(limit 16384, multiple of 8) and has not been measured on a Raspberry Pi.
