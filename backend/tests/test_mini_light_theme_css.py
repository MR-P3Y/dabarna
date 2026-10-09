from __future__ import annotations

import re
from pathlib import Path


MINI_DIR = Path(__file__).resolve().parents[1] / "app" / "static" / "mini"
CSS = (MINI_DIR / "styles.css").read_text(encoding="utf-8")
INDEX = (MINI_DIR / "index.html").read_text(encoding="utf-8")


def _relative_luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]

    def linearize(channel: float) -> float:
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linearize(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(a: str, b: str = "#ffffff") -> float:
    l1 = _relative_luminance(a)
    l2 = _relative_luminance(b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_light_theme_semantic_text_colors_meet_normal_text_contrast() -> None:
    variables = dict(
        re.findall(r"--(ui-[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", CSS)
    )
    expected = {
        "ui-success-text",
        "ui-danger-text",
        "ui-warning-text",
        "ui-info-text",
        "ui-strong-text",
        "ui-muted-text",
    }
    assert expected <= variables.keys()

    for name in expected:
        assert _contrast_ratio(variables[name]) >= 4.5, (
            f"{name}={variables[name]} is too low contrast on a light surface"
        )


def test_critical_light_theme_overrides_exist() -> None:
    required = (
        'html[data-theme="light"] .withdraw-wallet-status.ok',
        'html[data-theme="light"] .withdraw-wallet-status.bad',
        'html[data-theme="light"] .withdraw-wallet-grid b',
        'html[data-theme="light"] .admin-withdraw-item .withdraw-wallet-grid.muted',
        'html[data-theme="light"] .admin-wdr-wallet-refresh-btn',
        'html[data-theme="light"] .withdraw-proof-file-picker span',
        'html[data-theme="light"] .withdraw-proof-preview-card span',
        'html[data-theme="light"] .wallet-guide-badge',
        'html[data-theme="light"] .crypto-network-health',
        'html[data-theme="light"] .crypto-payment-status.is-pending',
        'html[data-theme="light"] .game-state.running',
        'html[data-theme="light"] #adminSendLiveBtn:not(:disabled)',
    )
    for selector in required:
        assert selector in CSS, f"missing light-theme override: {selector}"


def test_stylesheet_cache_token_matches_contrast_release() -> None:
    assert "./styles.css?v=mini-light-contrast-20261009-1" in INDEX
