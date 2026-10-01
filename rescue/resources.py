"""Explicit development-only scheduling for a memory-constrained Mac."""
from contextlib import contextmanager
import os
import re
import subprocess
import sys


@contextmanager
def model_resources(model):
    profile=os.getenv('RESCUE_SERIAL_COLIMA','')
    if not profile:
        yield
        return
    if (os.getenv('RESCUE_ENV')=='production' or sys.platform!='darwin'
        or not re.fullmatch(r'[a-z][a-z0-9-]{0,40}',profile)
        or os.getenv('RESCUE_DOCKER_CONTEXT')!='colima-'+profile
        or os.getenv('RESCUE_MODEL_PROVIDER','ollama')!='ollama'
        or os.getenv('RESCUE_MODEL_URL','http://127.0.0.1:11434') not in ['http://127.0.0.1:11434','http://localhost:11434']):
        raise RuntimeError('Serial scheduling requires an explicitly selected local development Colima worker and Ollama')
    subprocess.run(['colima','stop',profile],check=True,timeout=120,capture_output=True)
    try:
        yield
    finally:
        try:
            subprocess.run(['ollama','stop',model],timeout=30,capture_output=True)
        finally:
            subprocess.run(['colima','start',profile,'--memory','1.5','--activate=false','--ssh-config=false','--downloader','curl'],check=True,timeout=180,capture_output=True)
