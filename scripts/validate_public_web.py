# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio
import json
from pathlib import Path
from uuid import uuid4
from hydra.tools.definitions import ToolContext, WorkerCapabilities
from hydra.tools.public_web import web_search, web_read


async def main():
    ctx = ToolContext(task_id=uuid4(), capabilities=WorkerCapabilities(public_web=True))
    results = {"search": await web_search({"query": "Python asyncio official documentation", "engine": "brave"}, ctx),
               "read": await web_read({"url": "https://docs.python.org/3/library/asyncio.html"}, ctx)}
    results["read"]["text"] = results["read"]["text"][:1500]
    Path("docs/evidence/public-web-live-2026-09-30.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"search_status": results["search"]["status"], "engine": results["search"].get("engine"),
                      "results": len(results["search"]["results"]), "paid_api_used": False,
                      "read_status": results["read"]["status"], "read_chars": len(results["read"]["text"])}))


if __name__ == "__main__":
    asyncio.run(main())
