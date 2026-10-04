# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Stream one Common Pile stackv2_edu_filtered shard and keep permissive files of one language.

The dataset is ordered by language (Markdown first), so a generic streaming download
never reaches Python; shards 75-84 hold Python. Nothing downloaded here is executed.
"""
import argparse
import json
import urllib.request
import zlib
from pathlib import Path

URL = "https://huggingface.co/datasets/common-pile/stackv2_edu_filtered/resolve/main/stack-edu-{:04d}.json.gz"


def rows(shard: int):
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    request = urllib.request.Request(URL.format(shard), headers={"User-Agent": "HYDRA-corpus/1.0"})
    pending = b""
    with urllib.request.urlopen(request, timeout=120) as response:
        while chunk := response.read(1 << 20):
            pending += decoder.decompress(chunk)
            *lines, pending = pending.split(b"\n")
            for line in lines:
                if line.strip():
                    yield json.loads(line)
    if pending.strip():
        yield json.loads(pending)


# Default shard and output per language: shards 0-19 hold Markdown, 75-84 Python.
DEFAULTS = {"python": (77, 20000, "data/sources/code/stackv2_edu_python_sample.jsonl"),
            "markdown": (0, 91739, "data/sources/code/stackv2_edu_markdown_sample.jsonl")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=sorted(DEFAULTS), default="python")
    parser.add_argument("--shard", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    shard, limit, output = DEFAULTS[args.language]
    args.shard = shard if args.shard is None else args.shard
    args.limit = limit if args.limit is None else args.limit
    args.output = Path(output) if args.output is None else args.output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    kept = seen = 0
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        for row in rows(args.shard):
            seen += 1
            meta = row.get("metadata") or {}
            if (meta.get("language") or "").lower() != args.language or meta.get("license_type") != "permissive":
                continue
            if meta.get("is_vendor") or meta.get("is_generated"):
                continue
            out.write(json.dumps({
                "text": row["text"], "source": "common-pile/stackv2_edu_filtered", "shard": args.shard,
                "id": row.get("id"), "language": args.language, "license_type": meta.get("license_type"),
                "detected_licenses": meta.get("detected_licenses"), "repo_name": meta.get("repo_name"),
                "path": meta.get("path"), "revision_id": meta.get("revision_id"),
            }, ensure_ascii=False) + "\n")
            kept += 1
            if kept >= args.limit:
                break
    print(json.dumps({"seen": seen, "kept": kept, "output": str(args.output)}))


if __name__ == "__main__":
    main()
