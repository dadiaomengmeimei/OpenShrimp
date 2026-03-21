"""Configuration and constants for PPT Generator app."""

# File storage - absolute path is recommended for reliable file serving
# Can be set via environment variable PPT_STORAGE_DIR, defaults to ./ppt_storage
import os
PPT_STORAGE_DIR = os.environ.get("PPT_STORAGE_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "ppt_storage")))

# Base URL for generating downloadable links
# This should be set to the public server URL (e.g., "https://your-domain.com")
# Priority: 1. config parameter from platform  2. BASE_URL from config  3. relative URL
BASE_URL = os.environ.get("BASE_URL", "")

# PPT default settings
DEFAULT_SLIDE_WIDTH = 10  # inches
DEFAULT_SLIDE_HEIGHT = 7.5  # inches (16:9 aspect ratio)

# Slide layouts mapping
LAYOUT_TITLE = 0
LAYOUT_TITLE_AND_CONTENT = 1
LAYOUT_BLANK = 6

# Available themes
AVAILABLE_THEMES = {
    "business": {
        "name": "商务蓝",
        "description": "专业、简洁的商务风格，适合工作报告",
        "primary_color": "1F4E79",  # Dark blue
        "secondary_color": "2E75B6",  # Medium blue
        "accent_color": "5B9BD5",  # Light blue
        "font_title": "微软雅黑",
        "font_body": "微软雅黑",
    },
    "creative": {
        "name": "创意橙",
        "description": "活力、创新的设计风格，适合创意提案",
        "primary_color": "C55A11",  # Orange
        "secondary_color": "ED7D31",  # Light orange
        "accent_color": "F4B084",  # Peach
        "font_title": "思源黑体",
        "font_body": "微软雅黑",
    },
    "minimal": {
        "name": "极简白",
        "description": "简约、干净的设计风格，适合学术演讲",
        "primary_color": "404040",  # Dark gray
        "secondary_color": "808080",  # Medium gray
        "accent_color": "BFBFBF",  # Light gray
        "font_title": "思源黑体",
        "font_body": "思源黑体",
    },
    "dark": {
        "name": "深色科技",
        "description": "高端、科技感的设计风格，适合技术分享",
        "primary_color": "FFFFFF",  # White text
        "secondary_color": "D9D9D9",  # Light gray
        "accent_color": "4472C4",  # Blue accent
        "font_title": "微软雅黑",
        "font_body": "微软雅黑",
        "bg_color": "1a1a2e",  # Dark background
    },
    "nature": {
        "name": "自然绿",
        "description": "清新、环保的设计风格，适合生态主题",
        "primary_color": "375623",  # Dark green
        "secondary_color": "548235",  # Medium green
        "accent_color": "A9D18E",  # Light green
        "font_title": "微软雅黑",
        "font_body": "微软雅黑",
    },
}

# Default theme
DEFAULT_THEME = "business"

# Session timeout (seconds)
SESSION_TIMEOUT = 3600