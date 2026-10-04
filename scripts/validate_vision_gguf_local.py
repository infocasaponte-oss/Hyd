# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Real local smoke probes; these do not constitute a promotion benchmark."""
import asyncio
import base64
import hashlib
import json
import re
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from hydra.core.contracts import ModelRequest
from hydra.providers.ollama import OllamaProvider


async def main():
    root = Path("runtime/studio-validated")
    root.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 120, 200, 270), fill="red")
    draw.ellipse((410, 120, 560, 270), fill="blue")
    draw.text((150, 25), "HYDRA 7421", font=ImageFont.truetype("arial.ttf", 42), fill="black")
    path = root / "vision-fixture.png"
    image.save(path)
    encoded = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
    provider = OllamaProvider("http://127.0.0.1:11434", timeout_s=180)
    evidence = {"scope": "smoke tests only", "runs": []}
    async with httpx.AsyncClient(base_url="http://127.0.0.1:11434", timeout=30) as client:
        manifest = json.loads(Path("models/hydra-q5/build-manifest.json").read_text())
        digest = hashlib.sha256(Path(manifest["artifact"]).read_bytes()).hexdigest()
        show = (await client.post("/api/show", json={"model": "hydra-q5-v2"})).json()
        served = re.search(r"(?m)^FROM .*sha256[-:]([a-f0-9]{64})", show["modelfile"])
        if digest != manifest["sha256"] or not served or served[1] != digest:
            raise ValueError("GGUF served identity mismatch")
        evidence["gguf_sha256"] = digest
        cases = [("qwen3-vl:8b", "Devuelve JSON con text (texto visible), left (forma y color a la izquierda), right (forma y color a la derecha).", [encoded]),
                 ("hydra-q5-v2", "Responde exactamente: HYDRA operativo", []),
                 ("hydra-q5-v2", "Calcula 17 por 19. Responde solo el número.", [])]
        for model, prompt, images in cases:
            samples = []
            task = asyncio.create_task(provider.generate(model, ModelRequest(
                messages=[{"role": "user", "content": prompt, "images": images}], temperature=0,
                max_tokens=128, timeout_s=180,
                metadata={"runtime_options": {"think": False, "num_ctx": 4096, "num_gpu": 99, "keep_alive": 0}})))
            while not task.done():
                try:
                    samples.extend((await client.get("/api/ps")).json().get("models", []))
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(.5)
            try:
                answer = await task
                evidence["runs"].append({"model": model, "output": answer.content,
                    "latency_ms": answer.latency_ms, "output_tokens": answer.output_tokens,
                    "gpu_samples": [{k: s.get(k) for k in ("name", "size", "size_vram")} for s in samples[-3:]]})
            except Exception as exc:
                evidence["runs"].append({"model": model, "error": str(exc)})
            Path("docs/evidence/vision-gguf-live-2026-09-30.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(json.dumps(evidence["runs"][-1], ensure_ascii=False), flush=True)
    await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
