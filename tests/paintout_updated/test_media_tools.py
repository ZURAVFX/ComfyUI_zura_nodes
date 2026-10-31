"""Portable media tools must work without modifying the process PATH."""
import importlib.util
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('paintout_media_tools', Path(__file__).parents[2] / 'paintout/media_tools.py')
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)


class MediaToolsTests(unittest.TestCase):
    def test_existing_path_install_is_preserved(self):
        with patch.object(tools.shutil, 'which', return_value='/known/ffmpeg'):
            self.assertEqual(tools.find_media_tool('ffmpeg'), '/known/ffmpeg')

    def test_file_browser_install_finds_both_tools_without_path(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(tools.shutil, 'which', return_value=None):
            root = Path(directory)
            for name in ('ffmpeg', 'ffprobe'):
                binary = root / 'ffmpeg/bin' / (name + ('.exe' if os.name == 'nt' else ''))
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_bytes(b'fixture')
                binary.chmod(0o755)
                self.assertEqual(Path(tools.find_media_tool(name, root)), binary)

    def test_missing_tool_has_actionable_no_terminal_instructions(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(tools.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, 'No terminal or PATH change'):
                tools.find_media_tool('ffprobe', directory)

    def test_arbitrary_program_names_are_rejected(self):
        with self.assertRaises(ValueError):
            tools.find_media_tool('powershell')


if __name__ == '__main__':
    unittest.main()
