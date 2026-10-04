# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio
import json
from pathlib import Path
import httpx


async def main():
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post("http://127.0.0.1:18084/v1/chat/completions", json={"model": "hydra",
            "messages": [{"role": "user", "content": "Investiga en la web qué es asyncio usando https://docs.python.org/3/library/asyncio.html . Responde en una frase y cita esa URL."}]})
        result = {"http_status": response.status_code, "body": response.json()}
        Path("docs/evidence/studio-web-chat-live.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True)[:2500])
        response.raise_for_status()


if __name__ == "__main__":
    asyncio.run(main())
