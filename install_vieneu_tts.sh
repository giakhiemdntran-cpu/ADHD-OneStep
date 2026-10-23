#!/usr/bin/env bash
set -e
python -m pip install -U pip
python -m pip install -U vieneu sounddevice

echo
echo "VieNeu-TTS installed. Test with:"
echo "python - <<'PY'"
echo "from vieneu import Vieneu"
echo "v=Vieneu()"
echo "for i,c in enumerate(v.infer_stream('Xin chào, mình là OneStep.', voice='Mai Anh')):"
echo "    print(i, c.shape, c.dtype)"
echo "    if i >= 2: break"
echo "PY"
