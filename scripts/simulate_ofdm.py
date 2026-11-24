"""Simulate the OFDM link over SNR, without any radio.

Writes BER before and after FEC, BLER and throughput to a CSV file and a plot.
Usage: python scripts/simulate_ofdm.py [--frames 100] [--multipath]
"""
from __future__ import annotations

import argparse
import csv
from math import erfc, sqrt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pluto_monitor.dsp import ofdm
from pluto_monitor.dsp import single_carrier as sc
from pluto_monitor.dsp.channel import Channel

SNRS_DB = np.arange(0, 23, 1.0)
PATHS = ((0.0, 1.0), (3.4, 0.6j), (7.2, -0.35))
SERIES = (("theory", "Theory, AWGN before FEC", "#898781", "--", ""),
          ("ber", "Before FEC", "#2a78d6", "-", "o"),
          ("ber_coded", "After FEC", "#eb6834", "-", "s"),
          ("bler", "Frames lost (BLER)", "#1baf7a", "-", "^"))


def q(x: float) -> float:
    return 0.5 * erfc(x / sqrt(2))


def theory_ber(mod: sc.Modulation, snr_db: float) -> float:
    """Raw BER in AWGN; the signal uses 52 of 64 subcarriers."""
    g = 10 ** (snr_db / 10) * ofdm.N_FFT / ofdm.USED.size
    if mod is sc.QPSK:
        return q(sqrt(g))
    r = sqrt(g / 5)
    return 0.75 * q(r) + 0.5 * q(3 * r) - 0.25 * q(5 * r)


def simulate(mod, snr_db, args, rng) -> dict:
    frame = ofdm.OfdmFrame(mod, args.bits)
    channel = Channel(snr_db=snr_db, cfo_hz=args.cfo, paths=PATHS if args.multipath else ((0.0, 1.0),))
    wave = frame.waveform()
    runs = [
        ofdm.analyze(frame, channel.receive(wave, 2 * frame.samples + 16, args.rate, rng), args.rate)
        for _ in range(args.frames)
    ]

    def column(key: str, missing: float) -> np.ndarray:
        data = np.array([run[key] for run in runs], dtype=float)
        return np.where(np.isfinite(data), data, missing)

    return {
        "modulation": mod.name,
        "snr_db": snr_db,
        "theory": theory_ber(mod, snr_db),
        "ber": column("ber", 0.5).mean(),  # an undetected frame counts as guessing
        "ber_coded": column("ber_coded", 0.5).mean(),
        "bler": 1 - column("frame_ok", 0.0).mean(),
        "throughput_bps": column("throughput_bps", 0.0).mean(),
        "detected": np.isfinite([run["snr_db"] for run in runs]).mean(),
    }


def plot(rows: list[dict], path: Path, title: str) -> None:
    mods = list(dict.fromkeys(row["modulation"] for row in rows))
    figure, axes = plt.subplots(1, len(mods), figsize=(11, 4.6), sharey=True, facecolor="#fcfcfb")
    for axis, mod in zip(axes, mods):
        axis.set_facecolor("#fcfcfb")
        chosen = [row for row in rows if row["modulation"] == mod]
        for key, label, color, style, marker in SERIES:
            # Zero errors cannot be drawn on a log axis: the curve ends there.
            points = [(r["snr_db"], r[key]) for r in chosen if r[key] > 1e-6]
            if points:
                axis.plot(*zip(*points), style, color=color, marker=marker, markersize=6,
                          linewidth=2, label=label, markeredgecolor="#fcfcfb")
        axis.set_yscale("log")
        axis.set_ylim(1e-6, 1.2)
        axis.set_xlim(SNRS_DB[0], SNRS_DB[-1])
        axis.set_title(f"OFDM-{mod}", color="#0b0b0b")
        axis.set_xlabel("SNR per sample (dB)", color="#52514e")
        axis.grid(True, color="#e1e0d9", linewidth=0.8)
        axis.tick_params(colors="#52514e")
        for side in ("top", "right"):
            axis.spines[side].set_visible(False)
    axes[0].set_ylabel("Error rate", color="#52514e")
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", ncol=4, frameon=False)
    figure.suptitle(title, color="#0b0b0b")
    figure.tight_layout(rect=(0, 0.07, 1, 1))
    figure.savefig(path, dpi=130)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate the OFDM link over SNR")
    parser.add_argument("--frames", type=int, default=100, help="frames per SNR point")
    parser.add_argument("--bits", type=int, default=2048, help="payload bits per frame")
    parser.add_argument("--rate", type=float, default=2e6, help="sample rate (Hz)")
    parser.add_argument("--cfo", type=float, default=2000.0, help="carrier offset (Hz)")
    parser.add_argument("--multipath", action="store_true", help="three-path channel")
    parser.add_argument("--out", type=Path, default=Path("data/exports"))
    args = parser.parse_args()

    rng = np.random.default_rng(1)
    rows = []
    for mod in (sc.QPSK, sc.QAM16):
        for snr_db in SNRS_DB:
            row = simulate(mod, float(snr_db), args, rng)
            rows.append(row)
            print(f"{mod.name:6s} {snr_db:4.0f} dB  BER {row['ber']:.2e}  after FEC "
                  f"{row['ber_coded']:.2e}  BLER {row['bler']:.2f}  "
                  f"{row['throughput_bps'] / 1e6:.2f} Mb/s", flush=True)

    args.out.mkdir(parents=True, exist_ok=True)
    name = "ofdm_multipath" if args.multipath else "ofdm_awgn"
    with (args.out / f"{name}.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    title = "Coded OFDM, three-path channel" if args.multipath else "Coded OFDM, AWGN channel"
    plot(rows, args.out / f"{name}.png", f"{title} ({args.frames} frames per point, simulated)")
    print(f"Saved {args.out / name}.csv and .png")


if __name__ == "__main__":
    main()
