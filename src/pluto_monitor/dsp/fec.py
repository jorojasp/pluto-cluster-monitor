"""Forward error correction: CRC-32 and a rate-1/2, K=7 convolutional code.

Generators 133/171 (octal) as in IEEE 802.11, decoded with a soft Viterbi.
"""
from __future__ import annotations

import zlib

import numpy as np

CONSTRAINT = 7
TAIL_BITS = CONSTRAINT - 1
CRC_BITS = 32
_STATES = 1 << TAIL_BITS
_GENERATORS = (0o133, 0o171)
_INTERLEAVER_SEED = 7_331

# Register layout: newest bit is the most significant of the 7 register bits.
_register = np.arange(2 * _STATES)
_OUTPUT = np.array(
    [[bin(int(r) & g).count("1") & 1 for g in _GENERATORS] for r in _register], dtype=np.int8
)
# State s (6 newest bits) is reached by registers 2*s and 2*s+1, which differ
# in the bit about to leave the register.
_PREVIOUS = np.stack([_register[0::2], _register[1::2]], axis=1) & (_STATES - 1)
_SIGNS = 1.0 - 2.0 * np.stack([_OUTPUT[0::2], _OUTPUT[1::2]], axis=1)  # (state, branch, output)


def append_crc(bits: np.ndarray) -> np.ndarray:
    crc = zlib.crc32(np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes())
    tail = ((crc >> np.arange(CRC_BITS)[::-1]) & 1).astype(np.int8)
    return np.concatenate([np.asarray(bits, dtype=np.int8), tail])


def check_crc(bits_with_crc: np.ndarray) -> bool:
    return bool(np.array_equal(append_crc(bits_with_crc[:-CRC_BITS]), bits_with_crc))


def coded_length(message_bits: int) -> int:
    return 2 * (message_bits + TAIL_BITS)


def encode(bits: np.ndarray) -> np.ndarray:
    """Terminated convolutional code: two output bits per input or tail bit."""
    padded = np.concatenate([np.zeros(TAIL_BITS, int), np.asarray(bits, int), np.zeros(TAIL_BITS, int)])
    windows = np.lib.stride_tricks.sliding_window_view(padded, CONSTRAINT)
    # Window order is oldest to newest, so the newest bit gets the top weight.
    registers = windows @ (1 << np.arange(CONSTRAINT))
    return _OUTPUT[registers].reshape(-1)


def decode(llr: np.ndarray) -> np.ndarray:
    """Soft Viterbi. llr > 0 means bit 0. Returns the message without tail."""
    pairs = np.asarray(llr, dtype=np.float64).reshape(-1, 2)
    metric = np.full(_STATES, -np.inf)
    metric[0] = 0.0
    choices = np.empty((pairs.shape[0], _STATES), dtype=np.uint8)
    # Branch metrics of all steps at once: (step, state, branch).
    branch = np.einsum("to,sbo->tsb", pairs, _SIGNS)
    rows = np.arange(_STATES)
    for step in range(pairs.shape[0]):
        candidates = metric[_PREVIOUS] + branch[step]
        pick = candidates[:, 1] > candidates[:, 0]
        choices[step] = pick
        metric = candidates[rows, pick.astype(np.intp)]
    state = 0
    bits = np.empty(pairs.shape[0], dtype=np.int8)
    for step in range(pairs.shape[0] - 1, -1, -1):
        bits[step] = state >> (TAIL_BITS - 1)
        state = int(_PREVIOUS[state, choices[step, state]])
    return bits[:-TAIL_BITS]


def interleaver(length: int) -> np.ndarray:
    """Fixed permutation spreading neighboring coded bits over the frame."""
    return np.random.default_rng(_INTERLEAVER_SEED).permutation(length)
