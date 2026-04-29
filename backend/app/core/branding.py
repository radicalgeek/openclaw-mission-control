"""Branding configuration — loads branding.yaml from the backend root."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

# Default values match the AxiaCraft brand so a missing or partial file is fine.
#
# Semantic colour tokens (success/warning/danger/info/neutral) are tuned to
# work on either light or dark surfaces. The bg/border use rgba alpha so they
# tint the underlying surface; the fg is a saturated mid-tone that meets
# WCAG AA (>=4.5:1) on the OAG dark surfaces (#111111 / #1a1a1a) and >=3:1
# on default white. Deployments that need different hues override via
# BRANDING_<FIELD> env vars (e.g. BRANDING_SUCCESS_FG=#22c55e).
_DEFAULTS: dict[str, str] = {
    "product_name": "Product Foundry",
    "company_name": "AxiaCraft",
    "full_title": "AxiaCraft Product Foundry",
    "description": "AI product engineering command center.",
    "accent_color": "#c9972a",
    "accent_strong": "#d4a82e",
    "accent_soft": "rgba(201, 151, 42, 0.18)",
    "accent_foreground": "#ffffff",
    "accent_text_on_soft": "#d4a82e",
    "bg": "",
    "surface": "",
    "sidebar_bg": "",
    "card_bg": "",
    # Surface variants — used by form inputs, pressed states, hover bgs.
    # Empty string = fall back to globals.css :root default (AxiaCraft navy).
    # Deployments override via BRANDING_SURFACE_MUTED / BRANDING_SURFACE_STRONG.
    "surface_muted": "",
    "surface_strong": "",
    # Border tokens — let deployments tint borders with their brand if desired.
    "border": "",
    "border_strong": "",
    "logo_path": "/axiacraft-logo.png",
    "copyright_holder": "AxiaCraft",
    # Semantic tokens — success (green family).
    "success_bg": "rgba(34, 197, 94, 0.15)",
    "success_fg": "#4ade80",
    "success_border": "rgba(34, 197, 94, 0.35)",
    # Warning (amber family) — pending / in-progress / medium priority.
    "warning_bg": "rgba(245, 158, 11, 0.15)",
    "warning_fg": "#fbbf24",
    "warning_border": "rgba(245, 158, 11, 0.35)",
    # Danger (rose family) — blocked / failed / high priority / errors.
    "danger_bg": "rgba(244, 63, 94, 0.15)",
    "danger_fg": "#fb7185",
    "danger_border": "rgba(244, 63, 94, 0.35)",
    # Info (blue family) — review / in-flight / lead notices.
    "info_bg": "rgba(96, 165, 250, 0.15)",
    "info_fg": "#93c5fd",
    "info_border": "rgba(96, 165, 250, 0.35)",
    # Neutral (slate family) — defaults / inactive / role tags.
    "neutral_bg": "rgba(148, 163, 184, 0.15)",
    "neutral_fg": "#cbd5e1",
    "neutral_border": "rgba(148, 163, 184, 0.35)",
}

_BRANDING_FILE = Path(__file__).parent.parent.parent / "branding.yaml"


class BrandingConfig(BaseModel):
    """Deployment-wide branding configuration loaded from branding.yaml."""

    product_name: str = Field(default=_DEFAULTS["product_name"])
    company_name: str = Field(default=_DEFAULTS["company_name"])
    full_title: str = Field(default=_DEFAULTS["full_title"])
    description: str = Field(default=_DEFAULTS["description"])
    accent_color: str = Field(default=_DEFAULTS["accent_color"])
    accent_strong: str = Field(default=_DEFAULTS["accent_strong"])
    accent_soft: str = Field(default=_DEFAULTS["accent_soft"])
    accent_foreground: str = Field(default=_DEFAULTS["accent_foreground"])
    accent_text_on_soft: str = Field(default=_DEFAULTS["accent_text_on_soft"])
    bg: str = Field(default=_DEFAULTS["bg"])
    surface: str = Field(default=_DEFAULTS["surface"])
    sidebar_bg: str = Field(default=_DEFAULTS["sidebar_bg"])
    card_bg: str = Field(default=_DEFAULTS["card_bg"])
    surface_muted: str = Field(default=_DEFAULTS["surface_muted"])
    surface_strong: str = Field(default=_DEFAULTS["surface_strong"])
    border: str = Field(default=_DEFAULTS["border"])
    border_strong: str = Field(default=_DEFAULTS["border_strong"])
    logo_path: str = Field(default=_DEFAULTS["logo_path"])
    copyright_holder: str = Field(default=_DEFAULTS["copyright_holder"])
    # Semantic colour tokens — see _DEFAULTS comment above for usage notes.
    success_bg: str = Field(default=_DEFAULTS["success_bg"])
    success_fg: str = Field(default=_DEFAULTS["success_fg"])
    success_border: str = Field(default=_DEFAULTS["success_border"])
    warning_bg: str = Field(default=_DEFAULTS["warning_bg"])
    warning_fg: str = Field(default=_DEFAULTS["warning_fg"])
    warning_border: str = Field(default=_DEFAULTS["warning_border"])
    danger_bg: str = Field(default=_DEFAULTS["danger_bg"])
    danger_fg: str = Field(default=_DEFAULTS["danger_fg"])
    danger_border: str = Field(default=_DEFAULTS["danger_border"])
    info_bg: str = Field(default=_DEFAULTS["info_bg"])
    info_fg: str = Field(default=_DEFAULTS["info_fg"])
    info_border: str = Field(default=_DEFAULTS["info_border"])
    neutral_bg: str = Field(default=_DEFAULTS["neutral_bg"])
    neutral_fg: str = Field(default=_DEFAULTS["neutral_fg"])
    neutral_border: str = Field(default=_DEFAULTS["neutral_border"])

    @property
    def app_slug(self) -> str:
        """Slugified product name for use as an application identifier."""
        return re.sub(r"[^a-z0-9]+", "-", self.product_name.lower()).strip("-")


def _apply_env_overrides(config: BrandingConfig) -> BrandingConfig:
    """Override any branding field with a matching BRANDING_<FIELD> env var.

    For example, ``BRANDING_DESCRIPTION="OAG tagline"`` overrides
    ``description`` without rebuilding the image or editing branding.yaml.
    All field names are upper-cased with the ``BRANDING_`` prefix:
    ``BRANDING_PRODUCT_NAME``, ``BRANDING_COMPANY_NAME``, etc.
    """
    import os

    overrides: dict[str, str] = {}
    for field in BrandingConfig.model_fields:
        env_key = f"BRANDING_{field.upper()}"
        value = os.environ.get(env_key)
        if value:
            overrides[field] = value
    if not overrides:
        return config
    return config.model_copy(update=overrides)


def load_branding(path: Optional[Path] = None) -> BrandingConfig:
    """Load branding configuration from a YAML file, falling back to defaults.

    Environment variables of the form ``BRANDING_<FIELD>`` (e.g.
    ``BRANDING_PRODUCT_NAME``) take precedence over anything in the YAML file,
    allowing runtime overrides without a rebuild.
    """
    target = path or _BRANDING_FILE
    if not target.exists():
        return _apply_env_overrides(BrandingConfig())

    try:
        import yaml  # type: ignore[import-untyped]

        raw: dict[str, str] = yaml.safe_load(target.read_text()) or {}
        config = BrandingConfig(**{k: v for k, v in raw.items() if k in BrandingConfig.model_fields})
        return _apply_env_overrides(config)
    except Exception:  # noqa: BLE001
        # Branding file is optional — fall back to defaults on any parse error.
        return _apply_env_overrides(BrandingConfig())


@lru_cache(maxsize=1)
def get_branding() -> BrandingConfig:
    """Return the cached deployment-wide branding config, loaded once at startup."""
    return load_branding()
