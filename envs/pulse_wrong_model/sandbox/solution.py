"""Starter solution for pulse_wrong_model. Edit freely; keep solve(data) -> dict.

As shipped it behaves like the trivial baseline: it trusts the design model and returns the
design pulse with "changed": False. The helpers implement the Hamiltonian, the traces and the
gate metric exactly as TASK.md states them.
"""
import numpy as np

TWO_PI = 2.0 * np.pi


def hamiltonians(u, alpha_ghz, scale_ghz, delta_ghz=0.0, levels=4, compression=0.0):
    """H_k for requested samples u_k = I + iQ, rotating frame of the drive; delta = f01 -
    f_drive. The line delivers u (1 - compression |u|^2)."""
    b = np.diag(np.sqrt(np.arange(1, levels)), 1).astype(complex)
    X, Y = b + b.conj().T, 1j * (b.conj().T - b)
    n = np.arange(levels)
    h0 = np.diag(TWO_PI * (n * delta_ghz + 0.5 * n * (n - 1) * alpha_ghz))
    u = np.asarray(u, dtype=complex)
    u = u * (1.0 - compression * np.abs(u) ** 2)
    return h0 + 0.5 * TWO_PI * scale_ghz * (u.real[..., None, None] * X
                                            + u.imag[..., None, None] * Y)


def propagate(u, alpha_ghz, scale_ghz, dt_ns, delta_ghz=0.0, levels=4, compression=0.0):
    """Unitary of a piecewise-constant pulse (time is the last axis of u)."""
    w, V = np.linalg.eigh(hamiltonians(u, alpha_ghz, scale_ghz, delta_ghz, levels, compression))
    P = (V * np.exp(-1j * dt_ns * w)[..., None, :]) @ np.swapaxes(V.conj(), -1, -2)
    U = P[..., 0, :, :]
    for k in range(1, P.shape[-3]):
        U = P[..., k, :, :] @ U
    return U


def x_infidelity(U):
    """Coherent 1 - average gate fidelity to X on the 0-1 block, free virtual Z after."""
    S = U[:2, :2]
    return 1.0 - (np.real(np.trace(S @ S.conj().T)) + (abs(S[0, 1]) + abs(S[1, 0])) ** 2) / 6.0


def rabi_trace(data, scale_ghz, delta_ghz=0.0, compression=0.0):
    """Noiseless 1 - P(|0>) for every Rabi amplitude."""
    u = np.asarray(data["rabi_amps"])[:, None] * np.asarray(data["rabi_envelope"])[None, :]
    U = propagate(u, data["alpha_ghz"], scale_ghz, data["rabi_dt_ns"], delta_ghz,
                  compression=compression)
    return 1.0 - np.abs(U[:, 0, 0]) ** 2


def ramsey_trace(data, scale_ghz, delta_ghz, t2_ns):
    """Noiseless P(|1>) of the Ramsey sequence (TASK.md formula)."""
    th = 0.5 * np.pi * scale_ghz / data["drive_scale_design_ghz"]
    tau = np.asarray(data["ramsey_delays_ns"])
    osc = np.exp(-tau / t2_ns) * np.cos(TWO_PI * (data["ramsey_offset_ghz"] + delta_ghz) * tau)
    return 0.5 * (1.0 - np.cos(th) ** 2 + np.sin(th) ** 2 * osc)


def solve(data):
    # TODO: fit data["rabi_p_exc"] to estimate the drive scale (and check the drive is linear).
    # TODO: fit data["ramsey_p1"] to estimate the qubit frequency drift.
    # TODO: decide whether the device differs from design (beyond the noise).
    # TODO: if it does, design a pulse for the device as you now know it.
    return {
        "pulse": np.asarray(data["nominal_pulse"], dtype=complex),
        "diagnosis": {
            "changed": False,
            "drive_scale": float(data["drive_scale_design_ghz"]),
            "f01_ghz": float(data["f01_design_ghz"]),
            "compression": 0.0,
        },
    }
