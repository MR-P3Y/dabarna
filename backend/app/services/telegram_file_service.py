from __future__ import annotations

from pathlib import Path
import os
import httpx # type: ignore

from fastapi import HTTPException # type: ignore
from app.core.config import TELEGRAM_BOT_TOKEN

TG_API = "https://api.telegram.org"

def download_telegram_file(file_id: str, dest_dir: Path, filename_prefix: str) -> str:
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not set")

    # 1) getFile
    url = f"{TG_API}/bot{TELEGRAM_BOT_TOKEN}/getFile"
    try:
        r = httpx.get(url, params={"file_id": file_id}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"telegram getFile failed: {e}")

    if not data.get("ok") or not data.get("result") or not data["result"].get("file_path"):
        raise HTTPException(status_code=400, detail="invalid telegram file_id")

    file_path = data["result"]["file_path"]
    ext = os.path.splitext(file_path)[1] or ".jpg"

    # 2) download file
    file_url = f"{TG_API}/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"{filename_prefix}{ext}"

    try:
        with httpx.stream("GET", file_url, timeout=30) as resp:
            resp.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"telegram file download failed: {e}")

    return str(out_path)
