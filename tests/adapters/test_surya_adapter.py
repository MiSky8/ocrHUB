from unittest.mock import MagicMock, patch

import pytest

from ocrhub.adapters.surya_adapter import SuryaAdapter


def test_available_false_when_surya_not_installed():
    with patch.dict("sys.modules", {"surya": None, "surya.recognition": None, "surya.detection": None}):
        assert SuryaAdapter().available() is False


def test_extract_uses_recognition_predictor(sample_image_bytes):
    adapter = SuryaAdapter()

    fake_line = MagicMock(text="OCRHUB TEST", confidence=0.95)
    fake_prediction = MagicMock(text_lines=[fake_line])

    fake_recognition_cls = MagicMock(return_value=MagicMock(return_value=[fake_prediction]))
    fake_detection_cls = MagicMock(return_value=MagicMock())

    with patch.object(SuryaAdapter, "_recognition_predictor_cls", fake_recognition_cls), patch.object(
        SuryaAdapter, "_detection_predictor_cls", fake_detection_cls
    ):
        result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.ok is True
    assert "OCRHUB TEST" in result.text
    assert result.pages[0].confidence == pytest.approx(0.95)
