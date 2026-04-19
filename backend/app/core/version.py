"""Application name and version constants."""

from app.core.branding import get_branding

APP_NAME = get_branding().app_slug
APP_VERSION = "0.1.0"
