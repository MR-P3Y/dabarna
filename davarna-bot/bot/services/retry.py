import asyncio

async def retry_async(fn, attempts: int = 3, delay_sec: float = 1.0):
    last = None
    for i in range(attempts):
        try:
            return await fn()
        except Exception as e:
            last = e
            if i < attempts - 1:
                await asyncio.sleep(delay_sec)
    raise last
