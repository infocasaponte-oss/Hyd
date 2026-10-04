# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Independent contextual candidate scorer on local HYDRA Base weights.

One isolated causal encoder row per candidate; a learned scalar head reads the
last hidden state. No pointer boundaries, special decision tokens or text output.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from hydra.hyd.model import render
from hydra.training.base_corpus import file_sha256

FORMAT = "hyd-contextual-ranker/1"


class ContextRanker:
    def __init__(self, backbone, tokenizer, head, device, max_tokens=1024):
        self.backbone, self.tokenizer, self.head = backbone, tokenizer, head
        self.device, self.max_tokens = device, max_tokens
        self.temperature, self.training, self.revision = 1.0, {}, "untrained"
        self.backbone.eval()
        self.head.eval()

    def encode(self, state, instructions, label, description):
        body = render({"state": state, "instructions": instructions,
                       "candidate": {"id": label, "criterion": description}})
        ids = self.tokenizer.encode(body, add_special_tokens=False)
        if self.tokenizer.bos_token_id is not None:
            ids.insert(0, self.tokenizer.bos_token_id)
        if self.tokenizer.eos_token_id is not None:
            ids.append(self.tokenizer.eos_token_id)
        if len(ids) > self.max_tokens:
            raise ValueError("Hyd contextual row exceeds its trained token budget")
        return ids

    def hidden(self, encodings):
        import torch
        length = max(map(len, encodings))
        padded = [ids + [self.tokenizer.pad_token_id] * (length - len(ids)) for ids in encodings]
        input_ids = torch.tensor(padded, device=self.device)
        mask = torch.arange(length, device=self.device)[None, :] < torch.tensor([len(x) for x in encodings], device=self.device)[:, None]
        with torch.autocast(device_type=self.device.type, dtype=torch.bfloat16, enabled=self.device.type == "cuda"):
            hidden = self.backbone(input_ids=input_ids, attention_mask=mask, use_cache=False).last_hidden_state
        index = torch.tensor([len(x) - 1 for x in encodings], device=self.device)
        return hidden[torch.arange(len(encodings), device=self.device), index].float()

    def logits(self, state, instructions, options, deadline=None):
        import torch
        # Admit every row before doing expensive work. Never truncate candidates.
        encoded = {key: self.encode(state, instructions, key, value) for key, value in options.items()}
        self.last_input_tokens = sum(map(len, encoded.values()))
        result = {}
        with torch.inference_mode():
            for key, ids in encoded.items():
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Hyd contextual deadline exceeded")
                result[key] = float(self.head(self.hidden([ids])).reshape(-1)[0].cpu())
        return result

    def probabilities(self, state, instructions, options, deadline=None):
        import math
        logits = self.logits(state, instructions, options, deadline)
        peak = max(logits.values())
        weights = {key: math.exp((value - peak) / self.temperature) for key, value in logits.items()}
        total = math.fsum(weights.values())
        return {key: value / total for key, value in weights.items()}

    @classmethod
    def load(cls, path: Path):
        import math
        import torch
        from safetensors.torch import load_file
        from transformers import LlamaModel, AutoTokenizer
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != FORMAT or data.get("origin") != "HYDRA Base":
            raise ValueError("not a HYDRA-native contextual ranker")
        base = Path(data["base_directory"])
        if not base.is_absolute():
            base = (path.parent / base).resolve()
        head_path = path.parent / "head.safetensors"
        if (file_sha256(head_path) != data["head_sha256"]
                or file_sha256(base / "model.safetensors") != data["base_weights_sha256"]
                or file_sha256(base / "tokenizer.model") != data["tokenizer_sha256"]):
            raise ValueError("Hyd contextual model lineage checksum mismatch")
        if (type(data["temperature"]) not in (int, float) or not math.isfinite(data["temperature"])
                or data["temperature"] <= 0 or type(data["max_tokens"]) is not int
                or not 32 <= data["max_tokens"] <= 65536):
            raise ValueError("invalid contextual calibration or context budget")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True, trust_remote_code=False)
        backbone = LlamaModel.from_pretrained(base, local_files_only=True, use_safetensors=True).to(device)
        if tokenizer.pad_token_id is None or data["max_tokens"] > backbone.config.max_position_embeddings:
            raise ValueError("invalid contextual tokenizer or token budget")
        width = backbone.config.hidden_size
        head = torch.nn.Sequential(torch.nn.Linear(width, width // 2), torch.nn.GELU(), torch.nn.Linear(width // 2, 1)).to(device)
        head.load_state_dict(load_file(head_path, device=str(device)))
        if any(not torch.isfinite(p).all() for p in head.parameters()):
            raise ValueError("nonfinite Hyd head")
        model = cls(backbone, tokenizer, head, device, data["max_tokens"])
        model.temperature, model.training = data["temperature"], data["training"]
        model.revision = file_sha256(path)
        return model
