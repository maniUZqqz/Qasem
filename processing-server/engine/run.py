"""ورودیِ Blender:  blender -b --python engine/run.py -- --mode render --compiled job/compiled.json --out job/"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault('UP3D_ROOT', os.path.dirname(HERE))

from up3d_engine import main  # noqa: E402

main.entry()
