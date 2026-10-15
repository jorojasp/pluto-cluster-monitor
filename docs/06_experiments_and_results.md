# Experiments and results

## Lab validation: 2026-10-15

Setup: three Raspberry Pi 2 Model B Rev 1.1 boards running 32-bit Raspbian 13
(Trixie), Python 3.13.5, libiio 0.26, pyadi-iio 0.0.21, NumPy 2.2.4 and SciPy
1.15.3. The server used FastAPI 0.115.11 and Uvicorn 0.32.0. Two Plutos were
attached to each RX Pi and one to the TX/server Pi. Radio serial assignments
are recorded in the distributed configs.

Common settings: 2.4 GHz center frequency, 1 MS/s, manual RX gain 30 dB,
10 kHz SineWave and a requested 0.5 s acquisition period. Timing windows below
refer to the first acquired sample, not the earlier HTTP Start request.

These are exploratory hardware checks. Exact antenna separations and
orientations were not recorded; no RF power calibration or saturation
measurement was made. Both receiver Pis reported undervoltage. DC offsets,
receiver spurs and transient peaks remain open issues.

## Background and TX gain response

| Condition | Session ID |
| --- | --- |
| TX off | `427a66f64c8b40f599842a5e40dd9bf5` |
| TX on, -40 dB | `2641e0029c39405fa94495972d050be6` |
| TX on, -30 dB | `b4e5da86d1bd4a10b4ba06cfaaed59f5` |

Excluding the first 5 s of acquisition in each gain run:

| Radio | Median power at -40 dB | Median power at -30 dB | SNR increase |
| --- | ---: | ---: | ---: |
| A1 | -2.91 dB | -0.76 dB | +10.09 dB |
| A2 | -2.42 dB | +0.69 dB | +9.86 dB |
| B1 | -3.31 dB | -0.15 dB | +9.94 dB |
| B2 | -3.79 dB | -0.20 dB | +10.43 dB |

The SNR response tracks the 10 dB TX gain increase. Total IQ power increases
less because it also includes background and DC. Negative SNR values with TX
off describe detected background components, not proof of reception from TX.

The TX-off run contained 78 frames per group, the -40 dB run 86 and the -30 dB
run 52, with no gaps in the received sequence numbers. Acquisition interval
occasionally reached about 1.6 s despite the 0.5 s request; real-time timing
and additional receiver capacity are therefore not yet validated.

## Proximity to group A

Session `ecb8c68faa194c08b162d77e22dfb463`; TX gain -30 dB. The operator reported
holding TX over group A from approximately 8 to 25 s. In that window:

| Radio | Median total power | Median estimated SNR |
| --- | ---: | ---: |
| A1 | +6.03 dB | +7.99 dB |
| A2 | +9.60 dB | +11.92 dB |
| B1 | -2.54 dB | -6.86 dB |
| B2 | +1.50 dB | +2.30 dB |

The median of group-mean power was +8.09 dB for A and -0.05 dB for B, a
separation of about 8.1 dB. A decreased after TX was moved away. Both nodes
sent 70 frames with no sequence gaps.

## Proximity to group B

Session `aaa3a9f15edb4f4c98807df9109e7c88`; the same RF settings. Comparing the
same 8-25 s window:

| Radio | Median total power | Median estimated SNR |
| --- | ---: | ---: |
| A1 | -0.29 dB | -1.14 dB |
| A2 | -0.99 dB | -3.03 dB |
| B1 | +4.78 dB | +6.98 dB |
| B2 | +2.47 dB | +4.62 dB |

B's median group-mean power exceeded A's by 4.29 dB. B dominated much of the
2-32 s interval; its advantage decreased toward the end. Both nodes sent
79 frames with no sequence gaps. This supports position-sensitive group
comparison, but not a distance estimate or symmetric propagation model.

## Failure observation and remaining work

Session `fc39b55d58414f2d987f616de2de65b3` was interrupted by a LAN disconnection
and must not be used for a simultaneous group comparison. `rxpi2` terminated
on a name-resolution error; after reconnecting LAN, its process was restarted
and Stop returned the server to idle.

Observed peaks (including startup peaks above +30 dB) must not be equated with
useful tone power. A2 also exhibited variable DC in separate diagnostic reads.
Further work: distinguish DC/AC/tone power in exported diagnostics, identify
transients, improve source-specific tone qualification, recover network
failures automatically, and validate digital modulations on hardware.

Raw session JSONL files are kept under `data/logs/` on the server and backed up
locally; runtime measurements remain excluded from Git. The tables preserve
the summarized results without committing laboratory logs or generated plots.
