# MATLAB Prototype

## Overview

The original implementation of the project was developed in MATLAB and served as the first complete proof of concept. This version demonstrated that a low-cost SDR-based platform could support real-time multi-receiver signal analysis with practical value for education and research.

The MATLAB prototype integrated hardware control, signal processing, and user interaction into a single application flow.

## Main Capabilities

The MATLAB-based system provided the following core features:

- continuous visualization of received signal power,
- real-time SNR calculation,
- automatic identification of the strongest and weakest receiver,
- grouping of receivers into logical clusters,
- comparison between receiver groups,
- support for multiple transmission modes,
- practical SDR management tools such as USB reset,
- and export of GUI snapshots.

## Hardware Structure

The system was designed around ADALM-Pluto radios.

Typical roles were:

- **1 transmitter**
- **multiple receivers**
- **1 host computer running MATLAB**

The poster associated with the project showed an experimental setup using 10 receiver radios organized into two logical clusters, controlled through a central host computer.

## Supported Modes

The prototype supported:

- unmodulated sine transmission,
- BPSK,
- QPSK,
- and 16QAM.

This made the platform useful not only for power monitoring but also for studying digital communication behavior under real hardware conditions.

## Receiver Grouping

One of the most important ideas in the MATLAB version was the grouping of receivers into clusters. Instead of treating the receiver array as a flat list only, the application compared subsets of receivers, making it easier to analyze differences in signal quality across the setup.

This clustering approach laid the groundwork for future scalability.

## Graphical Interface

The MATLAB system included a GUI that allowed the user to:

- configure frequency and bandwidth,
- select the signal mode,
- start and stop receiver acquisition,
- start and stop the transmitter,
- view receiver metrics,
- inspect strongest and weakest radios per group,
- compare receiver groups,
- and export a screenshot of the interface.

The GUI also included live plots showing strongest and weakest signal trends by group.

## Signal Processing Logic

For the SineWave mode, the MATLAB version computed metrics directly from received samples.

For digital modulation modes, the system used separate receiver chains with logic for:

- frame synchronization,
- carrier and timing correction,
- preamble detection,
- channel correction,
- symbol decisions,
- and SNR estimation.

This modular separation by modulation type is important because it influences how the Python port should be staged.

## Why the MATLAB Version Matters

The MATLAB prototype is not being discarded. It remains the validated baseline for the migration effort.

Its importance is that it already proved:

- the hardware concept,
- the monitoring logic,
- the scalability idea,
- and the educational/research value of the system.

The Python backend should therefore be understood as the next development stage built on the MATLAB prototype, not as a completely separate project.

## Current Limitation of the MATLAB Prototype

Although the MATLAB system successfully demonstrated the concept, it also had structural limitations:

- many responsibilities were concentrated in a single application,
- the GUI and backend were tightly coupled,
- hardware indexing relied on assumptions that are fragile during reconnection,
- and the architecture was less suited for deployment outside a host-PC-centered environment.

These limitations are part of the reason for the Python migration.