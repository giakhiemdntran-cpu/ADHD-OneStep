import os
import subprocess
import sys

port = os.getenv("ONESTEP_ADMIN_PORT", "8501")
cmd = [
    sys.executable, "-m", "streamlit", "run", "giao_dien_quan_tri.py",
    "--server.address", "0.0.0.0",
    "--server.port", port,
    "--server.headless", "true",
]
raise SystemExit(subprocess.call(cmd))
