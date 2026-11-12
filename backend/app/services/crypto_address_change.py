"""Validate proposed deposit addresses. Proposals NEVER change active scanner settings."""
from __future__ import annotations

import base64
import hashlib
import re

ALLOWED_NETWORKS = ("TRON", "TON")
PENDING_PREFIX = "crypto_address_change_proposal:"


def _tron_address_valid(address: str) -> bool:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    if len(address) != 34 or address[0] != "T" or any(ch not in alphabet for ch in address):
        return False
    number = 0
    for ch in address:
        number = number * 58 + alphabet.index(ch)
    raw = number.to_bytes(25, "big", signed=False) if number.bit_length() <= 200 else b""
    if len(raw) != 25 or raw[0] != 0x41:
        return False
    checksum = hashlib.sha256(hashlib.sha256(raw[:21]).digest()).digest()[:4]
    return raw[21:] == checksum


def _crc16_xmodem(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def canonical_ton_address(address: str) -> str:
    """Mainnet account identity per TEP-2, without changing historical invoice strings."""
    if re.fullmatch(r"(?:0|-1):[0-9a-fA-F]{64}", address):
        return address.lower()
    if not re.fullmatch(r"[A-Za-z0-9_+/\-]{48}", address):
        raise ValueError("Invalid TON address format")
    try:
        raw = base64.urlsafe_b64decode(address)
    except (ValueError, base64.binascii.Error):
        raise ValueError("Invalid TON encoding") from None
    if len(raw) != 36 or int.from_bytes(raw[-2:], "big") != _crc16_xmodem(raw[:-2]):
        raise ValueError("Invalid TON checksum")
    if raw[0] not in (0x11, 0x51):
        raise ValueError("Testnet or unsupported TON address flag")
    if raw[1] not in (0, 255):
        raise ValueError("Unsupported TON workchain")
    return f"{0 if raw[1] == 0 else -1}:{raw[2:34].hex()}"


def same_crypto_destination(network: str, first: str, second: str) -> bool:
    if network == "TON":
        return canonical_ton_address(first) == canonical_ton_address(second)
    return first == second


def validate_crypto_destination(network: str, address: str) -> str:
    network = str(network or "").strip().upper()
    address = str(address or "").strip()
    if network not in ALLOWED_NETWORKS:
        raise ValueError("Unsupported network")
    if not address or len(address) > 128:
        raise ValueError("Empty or oversized address")
    if network == "TRON" and not _tron_address_valid(address):
        raise ValueError("Invalid TRON Base58Check address")
    if network == "TON":
        canonical_ton_address(address)
    return address


def proposal_key(network: str) -> str:
    if network not in ALLOWED_NETWORKS:
        raise ValueError("Unsupported network")
    return PENDING_PREFIX + network
