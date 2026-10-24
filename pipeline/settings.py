"""Shared environment loading; exported values take precedence over .env."""
import os
from pipeline.paths import PROJECT_ROOT

def load_environment() -> None:
    """Load .env from the project root if it exists (no dotenv package needed)."""
    env_path = PROJECT_ROOT / ".env"
    if not os.path.isfile(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value

