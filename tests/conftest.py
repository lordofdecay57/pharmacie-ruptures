# -*- coding: utf-8 -*-
"""Rend moteur_ruptures importable quel que soit le répertoire de lancement."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
