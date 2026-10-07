import os
import sys
import tempfile
from pathlib import Path

# Use a throw-away data folder so tests never touch your real stories.
_tmp = tempfile.mkdtemp(prefix="story-studio-test-")
os.environ["STORY_DATA_DIR"] = _tmp
os.environ.pop("APP_PASSWORD", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
