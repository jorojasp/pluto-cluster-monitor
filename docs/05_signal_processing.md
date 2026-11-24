# Signal processing and metrics

## Shared power reference

Total received IQ power is `mean(abs(iq)**2)`, converted with
`10*log10(power + epsilon)`. It includes the wanted signal, interference, noise
and DC offset. Values are relative to the input ADC sample units, not dBm.
Hardware RX gain must remain fixed during a distance or group comparison.

For group means, power is averaged in linear units before conversion to dB.
The strongest and weakest receivers are selected by total received power.
The strongest group is the group containing the single highest-power receiver,
not the group with the highest mean power. A transient can therefore affect
this selection; use recorded medians for the controlled comparisons.

## Transmission

The transmitter converts waveforms to DAC code amplitudes before calling
pyadi-iio. Target RMS is 8192 with a complex peak limit of 16384. This fixes the
previous unit-amplitude data being truncated to zero or one integer code.
Different modulation crest factors can cause the headroom limiter to reduce
drive. Hardware TX gain remains a separate setting.

## SineWave

The transmitted tone is rounded to a whole number of cycles per buffer, so the
repeated buffer has no phase jump (10 kHz becomes 10009.8 Hz with 4096 samples).

The estimator searches near the requested tone, allowing oscillator offset,
and gates on a spectral peak. It then fits a complex sinusoid and DC term.
SNR is fitted tone power divided by residual power; estimated noise is the
residual in the original IQ power reference. It no longer classifies the
variance of the sinusoid itself as noise.

The spectral gate is not proof of source identity: real receiver spurs were
observed with TX off and produced negative SNR estimates. Use TX-off/on and
controlled gain changes to establish that a component follows the intended TX.
The fitted frequency is available in the detailed DSP return value but is not
yet exported in the per-radio network metrics.

## BPSK, QPSK and 16QAM

All three share `dsp/single_carrier.py`. A frame is a 39-symbol Barker-derived
preamble followed by blocks of up to 32 payload symbols, each closed by 4 pilot
symbols. The payload is a fixed pseudo-random sequence, so BER can be measured;
mapping is Gray. Pulse shaping is circular because the radio repeats the buffer.

Reception searches the preamble jointly in time and carrier offset (up to
+/-40 kHz, less at low symbol rates), then refines fractional timing, frequency
and DC. Phase is interpolated between preamble and pilots, without symbol
decisions, so it does not slip at low SNR. Captures span two frames and always
contain a complete one.

SNR compares the recovered payload with the known symbols, so it stays valid when
decisions are wrong. Equivalent input-referred noise/error power is
`P_total / (1 + SNR_linear)`. It includes distortion and synchronization error and
is not a calibrated thermal-noise measurement. The matched filter gains
`10*log10(sps)` dB over the sample SNR. BER uses only pilots for amplitude and
phase. Without a detected frame, SNR, BER and CFO are unavailable.

Synthetic tests check SNR within 0.8 dB, BER against theory, carrier offsets up to
38 kHz, DC and short payloads. Reported SNR saturates around 30-38 dB, and a 25 ppm
sample-clock difference costs a few dB with long frames. Physical modulation
validation and calibration remain pending.

## Histories

The browser deduplicates frames using each group's sequence and timestamp.
Its 120-point history is separate from the full metric session log. Missing
estimates appear as gaps. The console path also supports Matplotlib history
and weakest/strongest PNG exports.

See [validation protocol](08_measurement_validation.md) and
[experimental results](06_experiments_and_results.md).
