# System Architecture

## General Overview

The system is designed as a scalable multi-SDR platform for real-time signal monitoring and analysis. It uses ADALM-Pluto radios to form a small wireless measurement network composed of:

- one transmitting node,
- multiple receiving nodes,
- and a central software layer for coordination, acquisition, processing, and output generation.

The first complete implementation was developed in MATLAB. The current development stage focuses on rebuilding the backend in Python while preserving the essential logic of the original system.

## High-Level Architecture

The platform can be described in terms of three main functional layers:

1. **Transmission layer**
2. **Reception layer**
3. **Processing and control layer**

### Transmission Layer

A single ADALM-Pluto radio acts as the transmitter. Depending on the selected mode, it can generate either:

- a continuous sine wave,
- or a digitally modulated waveform.

This transmitter serves as the reference source for the receiver array.

### Reception Layer

Multiple ADALM-Pluto radios act as receivers. These radios are organized into logical groups or clusters. The grouping allows the system to compare subsets of receivers and identify differences in received signal quality across the array.

The original MATLAB-based design considered clusters of up to nine radios each, allowing the system to scale up to large receiver arrays.

### Processing and Control Layer

In the original version, a central host computer running MATLAB was responsible for:

- device configuration,
- acquisition of IQ samples,
- signal processing,
- computation of power and SNR,
- real-time GUI updates,
- strongest/weakest receiver selection,
- cluster comparison,
- and utility functions such as USB reset.

In the Python version, these responsibilities are being split into backend modules to improve software structure.

## Original MATLAB Architecture

The MATLAB implementation combined many responsibilities inside a single application flow:

- parameter selection,
- GUI creation,
- transmitter control,
- receiver creation,
- acquisition loops,
- digital demodulation functions,
- metric computation,
- strongest/weakest selection,
- plotting,
- and hardware reset logic.

While this approach was effective for validating the proof of concept, it created a tightly coupled architecture that is harder to maintain and extend.

## Current Python Backend Architecture

The Python migration reorganizes the system into modules with clearer responsibilities.

### Configuration

This layer loads parameters such as:

- center frequency,
- sample rate,
- gains,
- number of receivers,
- logical group assignments,
- transmitter identity,
- and runtime behavior.

### Hardware Discovery

This layer resolves which physical radios are connected and maps stable identifiers such as serial numbers to the currently available connection URIs.

This was introduced because direct reliance on fixed USB indices is not robust when radios are disconnected and reconnected.

### Receiver and Transmitter Control

Separate classes handle:

- receiver initialization,
- transmitter initialization,
- sample acquisition,
- waveform transmission,
- and device cleanup.

### Acquisition Layer

The acquisition layer performs repeated reads from the receiver array and extracts measurement data from the incoming samples.

For the current stage of development, this layer is centered on the SineWave mode.

### Signal Processing Layer

This layer contains the logic for computing signal metrics and, in the future, digital demodulation and synchronization.

At the current stage, it focuses primarily on:

- received power,
- SNR estimation,
- strongest receiver identification,
- weakest receiver identification,
- and group-level comparison.

### History and Plotting

The backend stores short-term metric histories to enable offline or exportable plots of:

- strongest receiver behavior per group,
- weakest receiver behavior per group,
- and future additional time-domain summaries.

## Design Transition

The key architectural transition from MATLAB to Python can be summarized as follows:

- **MATLAB:** integrated GUI-centered prototype
- **Python:** modular backend-centered platform

This transition is important because the long-term goal is not only to reproduce the MATLAB behavior, but also to create a backend that can later support:

- a new visualization layer,
- remote or distributed receiver nodes,
- embedded execution,
- and more advanced experimental workflows.

## Long-Term Direction

The Python backend is being designed with future extensibility in mind. Possible future architectural extensions include:

- separating the transmitter and receiver roles across different machines,
- using a central aggregation node or server,
- adding support for embedded Linux platforms such as Raspberry Pi,
- and integrating positioning or network-aware analysis features.
