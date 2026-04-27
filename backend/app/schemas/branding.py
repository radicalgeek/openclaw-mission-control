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
    logo_path: str
    copyright_holder: str


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
    logo_path: Optional[str] = None
    copyright_holder: Optional[str] = None
