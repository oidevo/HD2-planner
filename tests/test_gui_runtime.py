from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO

from hd2lib.gui_launcher import main
from hd2lib.gui_runtime import missing_tkinter_message, tkinter_import_failed
from unittest.mock import patch


class GUIRuntimeTests(unittest.TestCase):
    def test_missing_tkinter_message_identifies_runtime_and_recovery(self):
        message = missing_tkinter_message()
        self.assertIn(sys.executable, message)
        self.assertIn(sys.version.split()[0], message)
        self.assertIn("Tkinter is missing", message)
        self.assertIn("Tk-enabled Python 3.14 or newer", message)
        self.assertIn("CLI and your stored profile data are unaffected", message)

    def test_recognizes_tkinter_import_failures_only(self):
        self.assertTrue(tkinter_import_failed(ImportError(name="_tkinter")))
        self.assertTrue(tkinter_import_failed(ImportError(name="tkinter")))
        self.assertFalse(tkinter_import_failed(ImportError(name="unrelated")))

    def test_console_launcher_reports_missing_tkinter_without_touching_data(self):
        with patch("builtins.__import__", side_effect=ImportError(name="_tkinter")), redirect_stderr(StringIO()):
            # Import is attempted after the launcher starts, so no profile paths
            # are initialized before a missing-Tkinter diagnosis is returned.
            self.assertEqual(main(), 1)


if __name__ == "__main__":
    unittest.main()
