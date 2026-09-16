from __future__ import annotations

from bot.services.api_client import ApiClient


async def get_draw_mode(api: ApiClient, game_id: int) -> dict:
    data = await api._request(
        "GET",
        f"/bot/admin/games/{int(game_id)}/draw-mode",
        headers=api.admin_headers(),
    )
    return data if isinstance(data, dict) else {}


async def set_draw_mode(
    api: ApiClient,
    game_id: int,
    *,
    draw_mode: str,
    interval_seconds: int | None = None,
) -> dict:
    data = await api._request(
        "PUT",
        f"/bot/admin/games/{int(game_id)}/draw-mode",
        json={
            "draw_mode": str(draw_mode).upper(),
            "interval_seconds": int(interval_seconds) if interval_seconds is not None else None,
        },
        headers=api.admin_headers(),
    )
    return data if isinstance(data, dict) else {}


async def pause_auto_draw(api: ApiClient, game_id: int) -> dict:
    data = await api._request(
        "POST",
        f"/bot/admin/games/{int(game_id)}/auto-draw/pause",
        headers=api.admin_headers(),
    )
    return data if isinstance(data, dict) else {}


async def resume_auto_draw(api: ApiClient, game_id: int) -> dict:
    data = await api._request(
        "POST",
        f"/bot/admin/games/{int(game_id)}/auto-draw/resume",
        headers=api.admin_headers(),
    )
    return data if isinstance(data, dict) else {}
