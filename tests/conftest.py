# -*- coding: utf-8 -*-
"""Rend commun/moteur_ruptures/stock_rotation importables quel que soit le
répertoire de lancement."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
