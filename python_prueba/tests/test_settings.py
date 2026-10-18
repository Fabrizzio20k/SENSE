"""Configuración de arranque: archivos temporales, sin iniciar servicios."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import Settings


class SettingsTests(unittest.TestCase):
    def test_project_dotenv_is_loaded_and_environment_has_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/".env").write_text('SENSE_MQTT_PORT=2883\nSENSE_MQTT_USERNAME="piloto # 1"\nSENSE_SLM_WARMUP=0\n', encoding="utf-8")
            with patch("runtime.ROOT", root), patch.dict(os.environ, {"SENSE_MQTT_PORT": "3883"}, clear=True):
                settings = Settings.environment()
                self.assertEqual(settings.mqtt_port, 3883)
                self.assertEqual(settings.mqtt_username, "piloto # 1")
                self.assertFalse(settings.slm_warmup)
                self.assertEqual(settings.data_dir, root/"data")

    def test_missing_dotenv_uses_defaults_and_does_not_load_example(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/".env.example").write_text("SENSE_MQTT_PORT=invalid\n", encoding="utf-8")
            with patch("runtime.ROOT", root), patch.dict(os.environ, {}, clear=True):
                settings = Settings.environment()
                self.assertEqual(settings.mqtt_port, 1883)
                self.assertTrue(settings.slm_warmup)

    def test_dotenv_cannot_bypass_local_model_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/".env").write_text("SENSE_SLM_URL=http://192.0.2.1:8080\n", encoding="utf-8")
            with patch("runtime.ROOT", root), patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "HTTP local"):
                    Settings.environment()


if __name__ == "__main__":
    unittest.main()
