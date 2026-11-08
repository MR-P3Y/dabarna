"""Pure address validation helpers for planned crypto rotation (#30).

No database writes, configuration reads, external requests, or Production switching.
A valid address does NOT imply the operator controls its private key.
"""
from __future__ import annotations

import base64
import hashlib
import re

_TRON_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_TRON_DIGITS = {c: i for i, c in enumerate(_TRON_ALPHABET)}
_TON_RAW = re.compile(r"^(-1|0):([0-9a-fA-F]{64})$")


class InvalidDepositAddress(ValueError):
    """The supplied address cannot safely be used as a deposit destination."""


def _tron_payload(address: str) -> bytes:
    if len(address) != 34 or not address.startswith("T"):
        raise InvalidDepositAddress("TRON address must be a 34-character mainnet T-address")
    value = 0
    for char in address:
        try:
            value = value * 58 + _TRON_DIGITS[char]
        except KeyError as exc:
            raise InvalidDepositAddress("TRON address has invalid Base58 characters") from exc
    raw = value.to_bytes(25, "big")
    body, checksum = raw[:-4], raw[-4:]
    expected = hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4]
    if body[0] != 0x41 or checksum != expected:
        raise InvalidDepositAddress("TRON mainnet prefix or Base58Check checksum is invalid")
    return body


def _crc16_xmodem(payload: bytes) -> bytes:
    crc = 0
    for value in payload:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc.to_bytes(2, "big")


def _normalize_ton(address: str) -> str:
    raw = _TON_RAW.fullmatch(address)
    if raw:
        workchain = int(raw.group(1))
        account = bytes.fromhex(raw.group(2))
        tag = 0x11
    else:
        if len(address) != 48 or not re.fullmatch(r"[a-zA-Z0-9_\-+/]{48}", address):
            raise InvalidDepositAddress("TON address must be 48-character friendly or WC:64-hex raw")
        try:
            decoded = base64.b64decode(address.replace("-", "+").replace("_", "/"), validate=True)
        except ValueError as exc:
            raise InvalidDepositAddress("Invalid TON base64 address") from exc
        if len(decoded) != 36 or decoded[-2:] != _crc16_xmodem(decoded[:-2]):
            raise InvalidDepositAddress("TON CRC16 checksum invalid")
        tag = decoded[0]
        if tag & 0x80:
            raise InvalidDepositAddress("TON test-only addresses cannot be used for mainnet")
        if tag not in (0x11, 0x51):
            raise InvalidDepositAddress("Unsupported TON address flags")
        workchain = int.from_bytes(decoded[1:2], "big", signed=True)
        account = decoded[2:34]
    if workchain not in (0, -1):
        raise InvalidDepositAddress("Unsupported TON workchain")
    payload = bytes([tag, workchain & 0xFF]) + account
    # Canonical user-friendly form keeps the original bounceability flag.
    return base64.urlsafe_b64encode(payload + _crc16_xmodem(payload)).decode().rstrip("=")


def validate_deposit_address(network: str, address: str) -> str:
    """Return canonical address; fail closed for unsupported networks and whitespace."""
    if not isinstance(network, str) or not isinstance(address, str):
        raise InvalidDepositAddress("Network and address must be strings")
    if address != address.strip() or not address or len(address) > 128:
        raise InvalidDepositAddress("Address has invalid whitespace or length")
    if network == "TRON":
        _tron_payload(address)
        return address
    if network == "TON":
        return _normalize_ton(address)
    raise InvalidDepositAddress("Unsupported deposit network")


def masked_address(address: str) -> str:
    if len(address) < 12:
        raise InvalidDepositAddress("Address too short to display safely")
    return address[:6] + "…" + address[-6:]
