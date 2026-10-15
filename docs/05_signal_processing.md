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

Digital paths generate a repeated 39-symbol Barker-derived preamble followed
by a random payload and pulse shaping. Reception uses matched filtering,
sample-phase selection, preamble correlation, phase-drift correction, a scalar
channel estimate and symbol decisions. The distributed receiver buffer spans
at least two cyclic frames to allow arbitrary capture alignment.

SNR uses decision-directed error relative to decided symbols. Equivalent
input-referred noise/error power is `P_total / (1 + SNR_linear)`. This shares
the raw IQ power reference but includes distortion and synchronization error;
it is not a calibrated thermal-noise measurement. Failed preamble detection
leaves SNR/error unavailable, while total power remains measurable.

These paths pass synthetic signal tests. Physical modulation validation,
frequency-offset robustness, BER and precision calibration remain pending.

## Histories

The browser deduplicates frames using each group's sequence and timestamp.
Its 120-point history is separate from the full metric session log. Missing
estimates appear as gaps. The console path also supports Matplotlib history
and weakest/strongest PNG exports.

See [validation protocol](08_measurement_validation.md) and
[experimental results](06_experiments_and_results.md).
