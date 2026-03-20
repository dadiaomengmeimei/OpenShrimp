"""
Configuration for PPT Generator app.
"""
from pathlib import Path

# App-specific settings
APP_ID = "ppt_generator"
APP_NAME = "PPT Generator"

# Storage configuration - Use absolute paths based on app location
APP_DIR = Path(__file__).parent
BACKEND_DIR = APP_DIR.parent.parent
DATA_DIR = BACKEND_DIR / "data" / "ppt_generator"
PPT_OUTPUT_DIR = DATA_DIR / "outputs"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
PPT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Default settings
DEFAULT_STYLE = "professional"
DEFAULT_LANGUAGE = "en"  # Changed to English as default
DEFAULT_SLIDE_COUNT = 10
MAX_SLIDE_COUNT = 50
MIN_SLIDE_COUNT = 3

# Supported styles
SUPPORTED_STYLES = ["professional", "creative", "minimal", "academic"]

# Supported languages
SUPPORTED_LANGUAGES = ["zh", "en"]