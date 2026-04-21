# Signal Processing and Metrics

## General Goal

The signal-processing layer of the project is responsible for extracting useful information from the received IQ data streams. Depending on the selected transmission mode, this includes either direct signal-quality metrics or more advanced demodulation-related processing.

At the current stage of the Python migration, the priority is to rebuild the SineWave measurement path before porting the more complex digital receiver chains.

## Core Metrics

The project currently focuses on two main metrics:

- **Received power**
- **Signal-to-Noise Ratio (SNR)**

These metrics are used to evaluate signal quality at each receiver and to compare receivers across logical groups.

## Power Measurement

Received power is computed from the IQ samples captured at each receiver. The general idea is to estimate the average signal energy over the received frame and convert it into a logarithmic dB representation.

This measurement is used to:

- compare receivers,
- identify strongest and weakest receivers,
- support group comparison,
- and produce historical plots.

## SNR Estimation

SNR is estimated differently depending on the signal mode.

### SineWave Mode

For the current Python backend, SineWave mode is the first measurement path being rebuilt. In this mode, the backend reads IQ samples and estimates:

- signal power,
- residual or noise-related power,
- and a practical SNR estimate for monitoring purposes.

This estimate is currently treated as an operational metric intended to preserve the monitoring behavior of the MATLAB prototype, rather than as a final precision laboratory-grade estimator.

### Digital Modulation Modes

In the MATLAB version, the digital receiver chains included additional steps such as:

- Barker-code-based frame synchronization,
- coarse frequency compensation,
- carrier synchronization,
- symbol timing recovery,
- preamble-based alignment,
- and SNR estimation after symbol correction and decision.

These chains are more complex and will be ported after the SineWave path is stable.

## Strongest and Weakest Receiver Selection

For each logical receiver group, the backend identifies:

- the receiver with the highest measured power,
- the receiver with the lowest measured power.

This is one of the most visible outputs of the system and is central to the cluster-comparison concept.

## Group Comparison

The project compares receiver groups in order to determine which subset of receivers is performing better under current conditions.

This comparison must remain consistent across development stages. One important implementation note is that the exact comparison rule should be explicitly documented and kept stable, since different definitions are possible, such as:

- comparison by group mean,
- comparison by strongest receiver in each group,
- or comparison by another aggregate metric.

This should be treated as a design decision and documented clearly.

## Time History and Plotting

The system stores short histories of measurement results so that metric evolution can be visualized over time.

For the current Python backend, the initial plotting focus is:

- strongest receiver power per group,
- weakest receiver power per group.

This reproduces one of the key behaviors of the original MATLAB interface while keeping the first backend implementation manageable.

## Why SineWave Comes First

The SineWave path is the best first target because it allows the project to validate:

- radio connectivity,
- continuous acquisition,
- metric computation,
- strongest/weakest selection,
- group comparison,
- and plotting,

without introducing the additional complexity of symbol synchronization and demodulation.

## Future Signal-Processing Work

After the SineWave path is stable, the next signal-processing steps are expected to be:

- BPSK chain migration,
- QPSK chain migration,
- 16QAM chain migration,
- improved SNR estimation,
- and possibly positioning- or protocol-related higher-level processing.
