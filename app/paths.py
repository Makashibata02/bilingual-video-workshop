"""Runtime files stay outside the public source tree."""
import os
from pathlib import Path
import sys


def app_root():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    override = os.environ.get('BILINGUAL_APP_ROOT')
    return Path(override).expanduser().resolve() if override else Path(__file__).resolve().parents[1] / '.local' / 'runtime'
