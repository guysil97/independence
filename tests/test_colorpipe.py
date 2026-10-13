import numpy as np
import pytest

from pipeline import colorpipe as cp


def test_slog3_matches_colour_science():
    colour = pytest.importorskip("colour")
    x = np.array([0.0, 0.005, 0.01125, 0.18, 0.9, 4.0, 30.0])
    ref = colour.models.log_encoding_SLog3(x)  # in_reflection=True: no 0.9 scaling
    np.testing.assert_allclose(cp.slog3_encode(x), ref, atol=1e-7)


def test_slog3_known_points():
    # Sony: 0% black = CV 95, 18% grey = CV 420
    assert cp.slog3_encode(0.0) * 1023 == pytest.approx(95.0, abs=1e-6)
    assert cp.slog3_encode(0.18) * 1023 == pytest.approx(420.0, abs=1e-6)


@pytest.mark.parametrize("transfer", ["rec709_display", "slog3"])
def test_round_trip_float(transfer):
    pipe = cp.ColorPipe({"color": {"input_transfer": transfer,
                                   "input_gamut": "rec709" if transfer == "rec709_display" else "sgamut3cine"}})
    code = np.linspace(0.0, 1.0, 100001, dtype=np.float64)
    lin = cp.bt1886_decode(code) if transfer == "rec709_display" else cp.slog3_decode(cp.full_to_legal(code))
    back = (cp.bt1886_encode(lin) if transfer == "rec709_display"
            else cp.legal_to_full(cp.slog3_encode(lin)))
    assert np.abs(back - code).max() < 1e-5
    # float32 public API as well
    c32 = code.astype(np.float32)
    assert np.abs(pipe.from_linear(pipe.to_linear(c32)) - c32).max() < 1e-5


def test_gamut_round_trip():
    m = cp._gamut_matrix("rec709", "sgamut3cine") @ cp._gamut_matrix("sgamut3cine", "rec709")
    np.testing.assert_allclose(m, np.eye(3), atol=1e-6)
