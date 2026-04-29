"""Schemas for the branding API endpoints."""

from __future__ import annotations

from typing import Optional

from sqlmodel import SQLModel


class BrandingRead(SQLModel):
    """Branding configuration returned by read endpoints."""

    product_name: str
    company_name: str
    full_title: str
    description: str
    accent_color: str
    accent_strong: str
    accent_soft: str
    accent_foreground: str
    accent_text_on_soft: str
    bg: str
    surface: str
    sidebar_bg: str
    card_bg: str
    surface_muted: str
    surface_strong: str
    border: str
    border_strong: str
    logo_path: str
    copyright_holder: str
    # Semantic tokens (success / warning / danger / info / neutral × bg / fg /
    # border). Used by status pills, dependency banners, agent type tags, and
    # any other surface that needs to convey severity / category without
    # hardcoding a Tailwind palette colour.
    success_bg: str
    success_fg: str
    success_border: str
    warning_bg: str
    warning_fg: str
    warning_border: str
    danger_bg: str
    danger_fg: str
    danger_border: str
    info_bg: str
    info_fg: str
    info_border: str
    neutral_bg: str
    neutral_fg: str
    neutral_border: str


class BrandingUpdate(SQLModel):
    """Partial branding overrides for an organization. All fields are optional."""

    product_name: Optional[str] = None
    company_name: Optional[str] = None
    full_title: Optional[str] = None
    description: Optional[str] = None
    accent_color: Optional[str] = None
    accent_strong: Optional[str] = None
    accent_soft: Optional[str] = None
    accent_foreground: Optional[str] = None
    accent_text_on_soft: Optional[str] = None
    bg: Optional[str] = None
    surface: Optional[str] = None
    sidebar_bg: Optional[str] = None
    card_bg: Optional[str] = None
    surface_muted: Optional[str] = None
    surface_strong: Optional[str] = None
    border: Optional[str] = None
    border_strong: Optional[str] = None
    logo_path: Optional[str] = None
    copyright_holder: Optional[str] = None
    success_bg: Optional[str] = None
    success_fg: Optional[str] = None
    success_border: Optional[str] = None
    warning_bg: Optional[str] = None
    warning_fg: Optional[str] = None
    warning_border: Optional[str] = None
    danger_bg: Optional[str] = None
    danger_fg: Optional[str] = None
    danger_border: Optional[str] = None
    info_bg: Optional[str] = None
    info_fg: Optional[str] = None
    info_border: Optional[str] = None
    neutral_bg: Optional[str] = None
    neutral_fg: Optional[str] = None
    neutral_border: Optional[str] = None
