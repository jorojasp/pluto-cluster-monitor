import numpy as np

from pluto_monitor.dsp.power import compute_linear_power, compute_power_db


def test_compute_linear_power_constant_signal() -> None:
    iq = np.ones(16, dtype=np.complex128)
    assert np.isclose(compute_linear_power(iq), 1.0)


def test_compute_power_db_constant_signal() -> None:
    iq = np.ones(16, dtype=np.complex128)
    assert np.isclose(compute_power_db(iq), 0.0, atol=1e-6)