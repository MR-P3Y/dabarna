from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

from bot.config import settings
from bot.services.error_i18n import localize_api_error_detail


class ApiError(Exception):
    def __init__(self, status: int, detail: str, *, raw_detail: str | None = None):
        self.status = status
        self.raw_detail = str(raw_detail if raw_detail is not None else detail)
        self.detail = localize_api_error_detail(self.raw_detail, status=status)
        super().__init__(f"API {status}: {self.detail}")


@dataclass
class ApiClient:
    base_url: str
    session: aiohttp.ClientSession
    bot_service_token: Optional[str] = None
    admin_api_token: Optional[str] = None
    super_admin_api_token: Optional[str] = None

    def _url(self, path: str) -> str:
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
        timeout_sec: float = 10.0,
    ) -> Any:
        h = {"Accept": "application/json"}
        if headers:
            h.update(headers)

        try:
            async with self.session.request(
                method,
                self._url(path),
                params=params,
                json=json,
                headers=h,
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            ) as resp:
                if 200 <= resp.status < 300:
                    if resp.content_type and "application/json" in resp.content_type:
                        return await resp.json()
                    return await resp.text()

                detail = None
                try:
                    data = await resp.json()
                    detail = data.get("detail") if isinstance(data, dict) else None
                except Exception:
                    pass

                if not detail:
                    try:
                        detail = await resp.text()
                    except Exception:
                        detail = "request failed"

                raise ApiError(resp.status, str(detail), raw_detail=str(detail))
        except asyncio.TimeoutError:
            raise ApiError(504, "backend timeout", raw_detail="backend timeout")
        except aiohttp.ClientError as e:
            raw = f"backend unavailable: {e.__class__.__name__}"
            raise ApiError(503, raw, raw_detail=raw)

    async def _request_bytes(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        timeout_sec: float = 20.0,
    ) -> bytes:
        h = {"Accept": "*/*"}
        if headers:
            h.update(headers)

        try:
            async with self.session.request(
                method,
                self._url(path),
                params=params,
                headers=h,
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            ) as resp:
                if 200 <= resp.status < 300:
                    return await resp.read()

                detail = None
                try:
                    data = await resp.json()
                    detail = data.get("detail") if isinstance(data, dict) else None
                except Exception:
                    pass

                if not detail:
                    try:
                        detail = await resp.text()
                    except Exception:
                        detail = "request failed"

                raise ApiError(resp.status, str(detail), raw_detail=str(detail))
        except asyncio.TimeoutError:
            raise ApiError(504, "backend timeout", raw_detail="backend timeout")
        except aiohttp.ClientError as e:
            raw = f"backend unavailable: {e.__class__.__name__}"
            raise ApiError(503, raw, raw_detail=raw)

    async def get_game(self, game_id: int) -> dict:
        return await self._request("GET", f"/games/{game_id}")

    async def get_game_state(self, game_id: int, last_n: int = 12) -> dict:
        return await self._request("GET", f"/games/{game_id}/state", params={"last_n": last_n})

    async def get_active_game_for_group(self, tg_group_id: int, *, tg_topic_id: int | None = None) -> dict:
        params: dict[str, int] | None = None
        if tg_topic_id is not None:
            params = {"tg_topic_id": int(tg_topic_id)}
        return await self._request("GET", f"/tg/groups/{tg_group_id}/active-game", params=params)

    async def ensure_active_game_for_group(
        self,
        tg_group_id: int,
        *,
        card_price: int,
        tg_topic_id: int | None = None,
    ) -> dict:
        params: dict[str, int] | None = None
        if tg_topic_id is not None:
            params = {"tg_topic_id": int(tg_topic_id)}
        return await self._request(
            "POST",
            f"/tg/groups/{int(tg_group_id)}/games/ensure-active",
            params=params,
            json={
                "tg_group_id": int(tg_group_id),
                "tg_topic_id": int(tg_topic_id) if tg_topic_id is not None else None,
                "card_price": int(card_price),
            },
            headers=self.admin_headers(),
        )

    def bot_headers(self, tg_user_id: int, tg_username: str | None = None) -> dict:
        h = {
            "X-Bot-Token": (self.bot_service_token or "").strip(),
            "X-Tg-User-Id": str(tg_user_id),
        }
        if tg_username:
            h["X-Tg-Username"] = tg_username
        return h

    def bot_service_headers(self) -> dict:
        token = (self.bot_service_token or "").strip()
        if not token:
            raise ApiError(401, "bot service token is not configured", raw_detail="bot service token is not configured")
        return {"X-Bot-Token": token}

    def admin_headers(self) -> dict:
        tok = (self.admin_api_token or settings.ADMIN_API_TOKEN or "").strip()
        if not tok:
            raise ApiError(401, "admin api token is not configured", raw_detail="admin api token is not configured")
        if not self.admin_api_token:
            self.admin_api_token = tok
        return {"X-Admin-Token": tok}

    def super_admin_headers(self) -> dict:
        tok = (self.super_admin_api_token or settings.SUPER_ADMIN_API_TOKEN or "").strip()
        if not tok:
            raise ApiError(
                401,
                "super admin api token is not configured",
                raw_detail="super admin api token is not configured",
            )
        if not self.super_admin_api_token:
            self.super_admin_api_token = tok
        return {"X-Admin-Token": tok}

    async def super_admin_list_admins(self) -> dict:
        data = await self._request(
            "GET",
            "/admin/rbac/admins",
            headers=self.super_admin_headers(),
        )
        if isinstance(data, dict):
            return data
        return {"total": 0, "items": []}

    async def super_admin_grant_admin(self, *, tg_user_id: int, role: str = "ADMIN") -> dict:
        return await self._request(
            "POST",
            "/admin/rbac/admins/grant",
            json={"tg_user_id": int(tg_user_id), "role": str(role).upper()},
            headers=self.super_admin_headers(),
        )

    async def super_admin_revoke_admin(self, *, tg_user_id: int, role: str = "ALL") -> dict:
        return await self._request(
            "POST",
            "/admin/rbac/admins/revoke",
            json={"tg_user_id": int(tg_user_id), "role": str(role).upper()},
            headers=self.super_admin_headers(),
        )

    async def super_admin_list_deposit_destinations(self) -> dict:
        data = await self._request(
            "GET",
            "/bot/admin/deposit-destinations",
            headers=self.super_admin_headers(),
        )
        if isinstance(data, dict):
            return data
        return {"total": 0, "items": []}

    async def super_admin_add_deposit_destination(
        self,
        *,
        title: str,
        account_name: str,
        bank_name: str,
        card_number: str,
        iban: str = "",
        account_number: str = "",
        is_active: bool = True,
    ) -> dict:
        return await self._request(
            "POST",
            "/bot/admin/deposit-destinations",
            json={
                "title": str(title),
                "account_name": str(account_name),
                "bank_name": str(bank_name),
                "card_number": str(card_number),
                "iban": str(iban or ""),
                "account_number": str(account_number or ""),
                "is_active": bool(is_active),
            },
            headers=self.super_admin_headers(),
        )

    async def super_admin_update_deposit_destination(
        self,
        destination_id: str,
        *,
        title: str,
        account_name: str,
        bank_name: str,
        card_number: str,
        iban: str = "",
        account_number: str = "",
        is_active: bool = True,
    ) -> dict:
        return await self._request(
            "PUT",
            f"/bot/admin/deposit-destinations/{destination_id}",
            json={
                "title": str(title),
                "account_name": str(account_name),
                "bank_name": str(bank_name),
                "card_number": str(card_number),
                "iban": str(iban or ""),
                "account_number": str(account_number or ""),
                "is_active": bool(is_active),
            },
            headers=self.super_admin_headers(),
        )

    async def super_admin_delete_deposit_destination(self, destination_id: str) -> dict:
        return await self._request(
            "DELETE",
            f"/bot/admin/deposit-destinations/{destination_id}",
            headers=self.super_admin_headers(),
        )


    async def super_admin_get_bank_deposit_settings(self) -> dict:
        data = await self._request(
            "GET",
            "/bot/admin/bank-deposit-settings",
            headers=self.super_admin_headers(),
        )
        return data if isinstance(data, dict) else {}

    async def super_admin_set_bank_deposit_settings(self, *, enabled: bool) -> dict:
        data = await self._request(
            "PUT",
            "/bot/admin/bank-deposit-settings",
            json={"enabled": bool(enabled)},
            headers=self.super_admin_headers(),
        )
        return data if isinstance(data, dict) else {}

    async def super_admin_get_crypto_settings(self) -> dict:
        data = await self._request(
            "GET",
            "/bot/admin/crypto-settings",
            headers=self.super_admin_headers(),
        )
        return data if isinstance(data, dict) else {}

    async def super_admin_set_crypto_settings(self, *, enabled: bool) -> dict:
        data = await self._request(
            "PUT",
            "/bot/admin/crypto-settings",
            json={"enabled": bool(enabled)},
            headers=self.super_admin_headers(),
        )
        return data if isinstance(data, dict) else {}

    async def super_admin_crypto_health(self) -> dict:
        data = await self._request(
            "GET",
            "/bot/admin/crypto-health",
            headers=self.super_admin_headers(),
            timeout_sec=30.0,
        )
        return data if isinstance(data, dict) else {}

    async def super_admin_crypto_reconciliation(self, *, from_at: str, to_at: str) -> dict:
        data = await self._request(
            "GET",
            "/bot/admin/crypto-reconciliation",
            params={"from_at": str(from_at), "to_at": str(to_at)},
            headers=self.super_admin_headers(),
            timeout_sec=45.0,
        )
        return data if isinstance(data, dict) else {}

    async def admin_list_games(
        self,
        *,
        status: str = "LOBBY|RUNNING",
        limit: int = 5,
        offset: int = 0,
        tg_group_id: int | None = None,
        tg_topic_id: int | None = None,
    ) -> dict:
        params = {"status": status, "limit": limit, "offset": offset}
        if tg_group_id is not None:
            params["tg_group_id"] = tg_group_id
        if tg_topic_id is not None:
            params["tg_topic_id"] = tg_topic_id

        return await self._request(
            "GET",
            "/bot/admin/games",
            params=params,
            headers=self.admin_headers(),
        )

    async def admin_get_game_report(self, game_id: int, *, events_limit: int | None = None) -> dict:
        params: dict[str, int] | None = None
        if events_limit is not None:
            params = {"events_limit": int(events_limit)}
        return await self._request(
            "GET",
            f"/bot/admin/games/{game_id}/report",
            params=params,
            headers=self.admin_headers(),
        )

    async def admin_get_games_sales_summary(
        self,
        *,
        from_at: str,
        to_at: str,
        tg_group_id: int | None = None,
        tg_topic_id: int | None = None,
    ) -> dict:
        params: dict[str, str | int] = {
            "from_at": str(from_at),
            "to_at": str(to_at),
        }
        if tg_group_id is not None:
            params["tg_group_id"] = int(tg_group_id)
        if tg_topic_id is not None:
            params["tg_topic_id"] = int(tg_topic_id)
        return await self._request(
            "GET",
            "/admin/reports/games-summary",
            params=params,
            headers=self.admin_headers(),
        )

    async def admin_get_game_live_link(self, game_id: int) -> dict:
        data = await self._request(
            "GET",
            f"/bot/admin/games/{int(game_id)}/live-link",
            headers=self.admin_headers(),
        )
        return data if isinstance(data, dict) else {}

    async def admin_set_game_live_link(self, game_id: int, *, url: str) -> dict:
        data = await self._request(
            "PUT",
            f"/bot/admin/games/{int(game_id)}/live-link",
            json={"url": str(url)},
            headers=self.admin_headers(),
        )
        return data if isinstance(data, dict) else {}

    async def admin_clear_game_live_link(self, game_id: int) -> dict:
        data = await self._request(
            "DELETE",
            f"/bot/admin/games/{int(game_id)}/live-link",
            headers=self.admin_headers(),
        )
        return data if isinstance(data, dict) else {}

    async def admin_list_game_participants(self, game_id: int, *, only_with_tg: bool = True) -> dict:
        data = await self._request(
            "GET",
            f"/bot/admin/games/{int(game_id)}/participants",
            params={"only_with_tg": 1 if only_with_tg else 0},
            headers=self.admin_headers(),
        )
        if isinstance(data, list):
            return {"items": data}
        if isinstance(data, dict):
            return data
        return {"items": []}

    async def admin_start_game(self, game_id: int, *, idempotency_key: str) -> dict:
        return await self._request(
            "POST",
            f"/bot/admin/games/{game_id}/start",
            json={"idempotency_key": idempotency_key},
            headers=self.admin_headers(),
        )

    async def admin_call_number(
        self,
        game_id: int,
        *,
        number: int,
        idempotency_key: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/bot/admin/games/{game_id}/call",
            json={"number": number, "idempotency_key": idempotency_key},
            headers=self.admin_headers(),
        )

    async def admin_undo_last_call(self, game_id: int, *, idempotency_key: str) -> dict:
        return await self._request(
            "POST",
            f"/bot/admin/games/{game_id}/undo-last-call",
            json={"idempotency_key": idempotency_key},
            headers=self.admin_headers(),
        )

    async def admin_set_game_status(
        self,
        game_id: int,
        *,
        status: str,
        idempotency_key: str,
        cancel_reason: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"status": status, "idempotency_key": idempotency_key}
        reason = str(cancel_reason or "").strip()
        if reason:
            payload["cancel_reason"] = reason
        return await self._request(
            "POST",
            f"/bot/admin/games/{game_id}/status",
            json=payload,
            headers=self.admin_headers(),
        )


    async def bot_get_user_restriction(self, tg_user_id: int, tg_username: str | None = None) -> dict:
        data = await self._request(
            "GET",
            f"/bot/users/{int(tg_user_id)}/restriction",
            headers=self.bot_headers(tg_user_id, tg_username),
        )
        return data if isinstance(data, dict) else {"active": False}

    async def bot_sync_user(self, tg_user_id: int, tg_username: str | None = None) -> dict:
        return await self._request(
            "POST",
            "/bot/sync-user",
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def bot_get_wallet(
        self,
        tg_user_id: int,
        tg_username: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        return await self._request(
            "GET",
            "/bot/wallet",
            params={"limit": limit, "offset": offset},
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def bot_create_withdraw_request(
        self,
        tg_user_id: int,
        tg_username: str | None,
        *,
        amount: int,
        full_name: str,
        iban: str | None,
        card_number: str,
        account_number: str | None,
        idempotency_key: str,
    ) -> dict:
        return await self._request(
            "POST",
            "/bot/withdraw-requests",
            json={
                "amount": amount,
                "full_name": full_name,
                "iban": iban,
                "card_number": card_number,
                "account_number": account_number,
                "idempotency_key": idempotency_key,
            },
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def bot_get_my_cards(
        self,
        tg_user_id: int,
        tg_username: str | None,
        *,
        game_id: int | None = None,
        page: int = 1,
        page_size: int = 12,
    ) -> dict:
        params = {"page": page, "page_size": page_size}
        if game_id is not None:
            params["game_id"] = game_id
        return await self._request(
            "GET",
            "/bot/my-cards",
            params=params,
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def bot_get_deposit_destination(self, tg_user_id: int, tg_username: str | None = None) -> dict:
        return await self._request(
            "GET",
            "/bot/deposit-destination",
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def bot_list_deposit_destinations(self, tg_user_id: int, tg_username: str | None = None) -> dict:
        data = await self._request(
            "GET",
            "/bot/deposit-destinations",
            headers=self.bot_headers(tg_user_id, tg_username),
        )
        if isinstance(data, dict):
            return data
        return {"total": 0, "items": []}

    async def bot_create_deposit_request(
        self,
        tg_user_id: int,
        tg_username: str | None,
        *,
        amount: int,
        destination_id: str | None = None,
    ) -> dict:
        body: dict[str, object] = {"amount": amount}
        if destination_id:
            body["destination_id"] = str(destination_id)
        return await self._request(
            "POST",
            "/bot/deposit-requests",
            json=body,
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def bot_upload_deposit_receipt(
        self,
        tg_user_id: int,
        tg_username: str | None,
        *,
        deposit_id: int,
        receipt_file_id: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/bot/deposit-requests/{deposit_id}/receipt",
            json={"receipt_file_id": receipt_file_id},
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def bot_get_deposit_request(
        self,
        tg_user_id: int,
        tg_username: str | None,
        *,
        deposit_id: int,
    ) -> dict:
        return await self._request(
            "GET",
            f"/bot/deposit-requests/{deposit_id}",
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def bot_crypto_options(self, tg_user_id: int, tg_username: str | None = None) -> dict:
        return await self._request(
            "GET",
            "/bot/crypto/options",
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def bot_create_crypto_deposit(
        self,
        tg_user_id: int,
        tg_username: str | None,
        *,
        amount_toman: int,
        network: str,
    ) -> dict:
        return await self._request(
            "POST",
            "/bot/crypto/deposits",
            json={"amount_toman": int(amount_toman), "network": str(network).upper()},
            headers=self.bot_headers(tg_user_id, tg_username),
            timeout_sec=20.0,
        )

    async def bot_get_crypto_deposit(
        self,
        tg_user_id: int,
        tg_username: str | None,
        *,
        invoice_id: int,
    ) -> dict:
        return await self._request(
            "GET",
            f"/bot/crypto/deposits/{int(invoice_id)}",
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def bot_claim_crypto_tx_hash(
        self,
        tg_user_id: int,
        tg_username: str | None,
        *,
        invoice_id: int,
        tx_hash: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/bot/crypto/deposits/{int(invoice_id)}/tx-hash",
            json={"tx_hash": str(tx_hash)},
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def admin_list_crypto_deposits(
        self,
        *,
        status: str = "NEEDS_REVIEW",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        data = await self._request(
            "GET",
            "/bot/admin/crypto-deposits",
            params={"status": str(status), "limit": int(limit), "offset": int(offset)},
            headers=self.admin_headers(),
        )
        return data if isinstance(data, dict) else {"items": []}

    async def admin_get_crypto_deposit(self, invoice_id: int) -> dict:
        return await self._request(
            "GET",
            f"/bot/admin/crypto-deposits/{int(invoice_id)}",
            headers=self.admin_headers(),
        )

    async def admin_approve_crypto_deposit(self, invoice_id: int) -> dict:
        return await self._request(
            "POST",
            f"/bot/admin/crypto-deposits/{int(invoice_id)}/approve",
            headers=self.admin_headers(),
        )

    async def admin_reject_crypto_deposit(self, invoice_id: int, *, reason: str) -> dict:
        return await self._request(
            "POST",
            f"/bot/admin/crypto-deposits/{int(invoice_id)}/reject",
            json={"reason": str(reason)},
            headers=self.admin_headers(),
        )

    async def bot_crypto_notifications(self, *, limit: int = 30) -> dict:
        data = await self._request(
            "GET",
            "/bot/crypto/notifications",
            params={"limit": int(limit)},
            headers=self.bot_service_headers(),
        )
        return data if isinstance(data, dict) else {
            "admin": [],
            "user": [],
            "pending": [],
            "variance": [],
        }

    async def bot_ack_crypto_notification(self, invoice_id: int, *, audience: str) -> dict:
        return await self._request(
            "POST",
            f"/bot/crypto/notifications/{int(invoice_id)}/{str(audience).lower()}/ack",
            headers=self.bot_service_headers(),
        )

    async def admin_crypto_health(self) -> dict:
        data = await self._request(
            "GET",
            "/bot/admin/crypto-health",
            headers=self.admin_headers(),
            timeout_sec=30.0,
        )
        return data if isinstance(data, dict) else {}

    async def admin_crypto_reconciliation(
        self,
        *,
        from_at: str,
        to_at: str,
    ) -> dict:
        data = await self._request(
            "GET",
            "/bot/admin/crypto-reconciliation",
            params={"from_at": str(from_at), "to_at": str(to_at)},
            headers=self.admin_headers(),
            timeout_sec=45.0,
        )
        return data if isinstance(data, dict) else {}

    async def bot_list_games(
        self,
        tg_user_id: int,
        tg_username: str | None = None,
        *,
        status: str = "LOBBY|ACTIVE",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        params = {"status": status, "limit": limit, "offset": offset}
        if settings.USER_FORUM_CHAT_ID is not None:
            params["tg_group_id"] = int(settings.USER_FORUM_CHAT_ID)
        elif settings.BOT_JOIN_GROUP_ID is not None:
            params["tg_group_id"] = int(settings.BOT_JOIN_GROUP_ID)

        data = await self._request(
            "GET",
            "/bot/games",
            params=params,
            headers=self.bot_headers(tg_user_id, tg_username),
        )
        if isinstance(data, list):
            return {"items": data}
        if isinstance(data, dict):
            return data
        return {"items": []}

    async def bot_purchase_cards(
        self,
        tg_user_id: int,
        tg_username: str | None,
        *,
        game_id: int,
        quantity: int,
        idempotency_key: str,
    ) -> dict:
        return await self._request(
            "POST",
            "/bot/purchase-cards",
            json={
                "game_id": int(game_id),
                "quantity": int(quantity),
                "idempotency_key": idempotency_key,
            },
            headers=self.bot_headers(tg_user_id, tg_username),
        )

    async def admin_list_deposits(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        created_from: str | None = None,
        created_to: str | None = None,
        min_amount: int | None = None,
        max_amount: int | None = None,
    ) -> dict:
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if created_from:
            params["created_from"] = created_from
        if created_to:
            params["created_to"] = created_to
        if min_amount is not None:
            params["min_amount"] = int(min_amount)
        if max_amount is not None:
            params["max_amount"] = int(max_amount)
        data = await self._request(
            "GET",
            "/bot/admin/deposit-requests",
            params=params,
            headers=self.admin_headers(),
        )
        if isinstance(data, list):
            return {"items": data}
        if isinstance(data, dict):
            return data
        return {"items": []}

    async def admin_get_deposit(self, deposit_id: int) -> dict:
        return await self._request(
            "GET",
            f"/bot/admin/deposit-requests/{int(deposit_id)}",
            headers=self.admin_headers(),
        )

    async def admin_get_deposit_receipt_bytes(self, deposit_id: int) -> bytes:
        return await self._request_bytes(
            "GET",
            f"/bot/admin/deposit-requests/{int(deposit_id)}/receipt",
            headers=self.admin_headers(),
        )

    async def admin_list_withdraws(
        self,
        *,
        status: str | None = "PENDING",
        limit: int = 100,
        offset: int = 0,
        created_from: str | None = None,
        created_to: str | None = None,
        min_amount: int | None = None,
        max_amount: int | None = None,
    ) -> dict:
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if created_from:
            params["created_from"] = created_from
        if created_to:
            params["created_to"] = created_to
        if min_amount is not None:
            params["min_amount"] = int(min_amount)
        if max_amount is not None:
            params["max_amount"] = int(max_amount)
        data = await self._request(
            "GET",
            "/bot/admin/withdraw-requests",
            params=params,
            headers=self.admin_headers(),
        )
        if isinstance(data, list):
            return {"items": data}
        if isinstance(data, dict):
            return data
        return {"items": []}

    async def admin_get_withdraw(self, withdraw_id: int) -> dict:
        return await self._request(
            "GET",
            f"/bot/admin/withdraw-requests/{int(withdraw_id)}",
            headers=self.admin_headers(),
        )

    async def admin_approve_withdraw(self, withdraw_id: int, *, idempotency_key: str) -> dict:
        return await self._request(
            "POST",
            f"/bot/admin/withdraw-requests/{int(withdraw_id)}/approve",
            json={"idempotency_key": idempotency_key},
            headers=self.admin_headers(),
        )

    async def admin_mark_withdraw_paid(self, withdraw_id: int, *, paid_tracking: str) -> dict:
        return await self._request(
            "POST",
            f"/bot/admin/withdraw-requests/{int(withdraw_id)}/paid",
            json={"paid_tracking": paid_tracking},
            headers=self.admin_headers(),
        )

    async def admin_reject_withdraw(self, withdraw_id: int, *, reason: str | None = None) -> dict:
        return await self._request(
            "POST",
            f"/bot/admin/withdraw-requests/{int(withdraw_id)}/reject",
            json={"reason": reason},
            headers=self.admin_headers(),
        )

    async def admin_approve_deposit(self, deposit_id: int, *, idempotency_key: str) -> dict:
        return await self._request(
            "POST",
            f"/bot/admin/deposit-requests/{int(deposit_id)}/approve",
            json={"idempotency_key": idempotency_key},
            headers=self.admin_headers(),
        )

    async def admin_reject_deposit(self, deposit_id: int, *, reason: str | None = None) -> dict:
        # Current backend endpoint does not consume reason; keep signature for caller compatibility.
        _ = reason
        return await self._request(
            "POST",
            f"/bot/admin/deposit-requests/{int(deposit_id)}/reject",
            headers=self.admin_headers(),
        )

    async def admin_manual_charge(self, *, telegram_user_id: int, amount: int, reason: str = "manual_charge") -> dict:
        return await self._request(
            "POST",
            "/bot/admin/manual-charge",
            json={
                "telegram_user_id": int(telegram_user_id),
                "amount": int(amount),
                "reason": reason,
            },
            headers=self.admin_headers(),
        )

    async def admin_users_search(
        self,
        *,
        tg_user_id: int | None = None,
        username: str | None = None,
        game_id: int | None = None,
        deposit_id: int | None = None,
        withdraw_id: int | None = None,
        limit: int = 30,
    ) -> dict:
        params: dict[str, object] = {"limit": int(limit)}
        if tg_user_id is not None:
            params["tg_user_id"] = int(tg_user_id)
        if username:
            params["username"] = str(username)
        if game_id is not None:
            params["game_id"] = int(game_id)
        if deposit_id is not None:
            params["deposit_id"] = int(deposit_id)
        if withdraw_id is not None:
            params["withdraw_id"] = int(withdraw_id)
        data = await self._request(
            "GET",
            "/admin/users/search",
            params=params,
            headers=self.admin_headers(),
        )
        if isinstance(data, dict):
            return data
        return {"total": 0, "items": []}

    async def admin_user_profile(self, tg_user_id: int) -> dict:
        return await self._request(
            "GET",
            f"/admin/users/{int(tg_user_id)}/profile",
            headers=self.admin_headers(),
        )

    async def admin_user_financial_history(self, tg_user_id: int, *, limit: int = 30) -> dict:
        return await self._request(
            "GET",
            f"/admin/users/{int(tg_user_id)}/financial-history",
            params={"limit": int(limit)},
            headers=self.admin_headers(),
        )

    async def admin_user_games_history(self, tg_user_id: int, *, limit: int = 30) -> dict:
        return await self._request(
            "GET",
            f"/admin/users/{int(tg_user_id)}/games-history",
            params={"limit": int(limit)},
            headers=self.admin_headers(),
        )

    async def admin_user_restrict(
        self,
        tg_user_id: int,
        *,
        reason: str,
        minutes: int | None = None,
        until: str | None = None,
        actions: list[str] | None = None,
    ) -> dict:
        body: dict[str, object] = {"reason": str(reason)}
        if minutes is not None:
            body["minutes"] = int(minutes)
        if until:
            body["until"] = str(until)
        if actions:
            body["actions"] = [str(x).upper() for x in actions if str(x or "").strip()]
        return await self._request(
            "POST",
            f"/admin/users/{int(tg_user_id)}/restrict",
            json=body,
            headers=self.admin_headers(),
        )

    async def admin_user_unrestrict(self, tg_user_id: int, *, reason: str | None = None) -> dict:
        body: dict[str, object] = {}
        if reason:
            body["reason"] = str(reason)
        return await self._request(
            "POST",
            f"/admin/users/{int(tg_user_id)}/unrestrict",
            json=body,
            headers=self.admin_headers(),
        )

    async def admin_user_wallet_adjust(
        self,
        tg_user_id: int,
        *,
        amount: int,
        reason: str,
        notify_user: bool = True,
    ) -> dict:
        return await self._request(
            "POST",
            f"/admin/users/{int(tg_user_id)}/wallet-adjust",
            json={
                "amount": int(amount),
                "reason": str(reason),
                "notify_user": bool(notify_user),
            },
            headers=self.admin_headers(),
        )

    async def admin_user_notify(
        self,
        tg_user_id: int,
        *,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = True,
    ) -> dict:
        return await self._request(
            "POST",
            f"/admin/users/{int(tg_user_id)}/notify",
            json={
                "text": str(text),
                "parse_mode": str(parse_mode),
                "disable_notification": bool(disable_notification),
            },
            headers=self.admin_headers(),
        )

    async def admin_user_compose_message(
        self,
        tg_user_id: int,
        *,
        kind: str,
        reason: str | None = None,
        amount: int | None = None,
        ref_id: int | None = None,
    ) -> dict:
        body: dict[str, object] = {"kind": str(kind)}
        if reason is not None:
            body["reason"] = str(reason)
        if amount is not None:
            body["amount"] = int(amount)
        if ref_id is not None:
            body["ref_id"] = int(ref_id)
        return await self._request(
            "POST",
            f"/admin/users/{int(tg_user_id)}/compose-message",
            json=body,
            headers=self.admin_headers(),
        )
