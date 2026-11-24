# Measurement corrections and experimental validation

## Power and TX amplitude
TX samples are expressed in DAC codes before passing them to pyadi-iio.
Waveforms target an RMS amplitude of 8192, with a complex peak limit of 16384.
This keeps average digital drive comparable between modulation modes while
preserving headroom. Waveforms with a higher crest factor are reduced to fit.
Invalid, empty and zero-power input is rejected.

Received power remains 10*log10(mean(abs(IQ)**2)). It includes signal,
noise and interference, and is in relative IQ units, not calibrated dBm.
RX hardware gain must stay fixed during a position comparison.

## SNR and estimated noise
SineWave uses spectral detection near the requested tone (allowing a frequency
offset), then fits a complex sinusoid and DC offset. Noise is the mean-square
residual. SNR is fitted tone power divided by residual power. Without a
significant spectral peak, SNR is unavailable instead of fitting pure noise.

Digital modes report EVM-based SNR against the known payload after synchronization.
The input-referred noise/error estimate is P_total/(1 + SNR_linear), so it
shares the raw IQ power reference. This is an equivalent estimate that includes
synchronization error and distortion; it is not a thermal-noise calibration.
A preamble correlation gate suppresses invalid demodulation estimates.
The receiver buffer spans at least two digital frames to capture a full frame
despite arbitrary alignment with the cyclic TX buffer.

Receiver spurs can pass the spectral gate even with TX off. Such estimates
do not identify the intended transmitter; compare controlled TX-off/on and
gain changes as described in the experimental results.

## Sessions and charts
Each Start attempt creates a JSONL session file under the server's
runtime.log_dir (data/logs by default). Records include start settings, each
incoming per-radio metrics message with sequence and timestamps, effective RX
settings, and the stop reason. These are metric histories, not saved raw IQ.
GET /api/status returns session_id and session_log.
The charts retain 120 acquisitions per group, deduplicate repeated WebSocket
snapshots, and use acquisition timestamps for elapsed seconds. A new session
resets chart history. Missing noise estimates are drawn as gaps.
The vertical scale is labeled in relative dB, spans at least 20 dB, and expands
without shrinking within a session.

## Controlled experiment
The deployed configuration starts with transmit_enabled=false and TX gain
-40 dB for the first corrected-amplitude test. Start/Stop remain manual.

1. Keep receiver positions, orientation, gain, frequency and sample rate fixed.
2. Choose SineWave and leave Enable transmitter unchecked. Start, record at
   least 20 seconds of background, then Stop.
3. Check Enable transmitter. Start with TX stationary at a reference position,
   using identical RX settings. Record at least 20 seconds, then Stop.
4. With the same settings, record a run near group A and a run near group B.
   Keep the antenna orientation comparable and note approximate distances.
5. Confirm a clear TX-on rise above background and a tone lock before
   interpreting group differences. Look for saturation or RF/USB errors.
6. Test BPSK, QPSK and 16QAM separately at a stationary reference position.
   Similar average power is expected with comparable drive; the spectrum,
   lock success and estimated SNR carry modulation-specific information.

Read the logged metrics after each step. A position-dependent increase in
power/SNR should be repeatable, but multipath and antenna orientation can
prevent monotonic instantaneous changes. Raspberry undervoltage remains a
known hardware limitation; these experiments do not establish long-term
stability until adequate power is available.

## Verification
Run: python -m pytest -q
Or: python -m unittest discover -s tests -p "test_*metrics.py" -v
And: python -m unittest discover -s tests -p test_distributed_measurements.py -v
Run with Node: node tests/test_frontend_history.mjs
The tests use synthetic signals and mocks, not RF transmission.
