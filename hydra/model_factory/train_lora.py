# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""LoRA / QLoRA fine-tuning and adapter merging (run as a separate process).

    python -m hydra.model_factory.train_lora job.json
    python -m hydra.model_factory.train_lora --merge <base> <adapter_dir> <output_dir>
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from hydra.training.verified_corpus import sha256


def normalize_job(raw: dict) -> dict:
    """Accept both Model Factory jobs and Training Lab recipes."""
    job = dict(raw)
    for key, alias, default in (("dataset", "train", None), ("r", "lora_rank", 8),
                                ("alpha", "lora_alpha", 16), ("dropout", "lora_dropout", 0.05),
                                ("max_seq_length", "max_length", 512),
                                ("gradient_accumulation", "gradient_accumulation", 4)):
        job.setdefault(key, job.get(alias, default))
    job.setdefault("target_modules", ["q_proj", "v_proj"])
    job.setdefault("seed", 42)
    if job.get("method") not in ("lora", "qlora"):
        raise ValueError("PEFT backend supports lora and qlora only")
    if not job.get("dataset"):
        raise ValueError("training dataset is required")
    return job


def message_rows(path: str, content_hash: str = ""):
    """Exclude heterogeneous verification metadata before Arrow schema inference."""
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield {"messages": json.loads(line)["messages"]}


def encode_response(tok, messages: list[dict], max_length: int) -> dict:
    """Mask only an exact token prefix; reject samples losing their answer."""
    if not messages or messages[-1]["role"] != "assistant":
        raise ValueError("SFT examples must end with an assistant answer")
    if not messages[-1].get("content", "").strip():
        raise ValueError("SFT assistant answer is empty")
    prompt = tok.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True, return_dict=False)
    full = tok.apply_chat_template(messages, tokenize=True, return_dict=False)
    if full[:len(prompt)] != prompt:
        raise ValueError("chat template token prefix mismatch")
    if len(full) > max_length:
        raise ValueError("sequence length truncates the assistant answer")
    if len(prompt) >= len(full):
        raise ValueError("sequence length truncates the entire assistant answer")
    eos = getattr(tok, "eos_token_id", None)
    end_ids = set(eos if isinstance(eos, (list, tuple)) else [eos]) - {None}
    for marker in ("<|im_end|>", "<|eot_id|>"):
        if marker in getattr(tok, "all_special_tokens", []):
            end_ids.add(tok.convert_tokens_to_ids(marker))
    answer = full[len(prompt):]
    while answer and tok.decode([answer[-1]]).isspace():
        answer = answer[:-1]
    if not answer or answer[-1] not in end_ids:
        raise ValueError("assistant answer lacks a supervised end-of-turn token")
    return {"input_ids": full, "attention_mask": [1] * len(full),
            "labels": [-100] * len(prompt) + full[len(prompt):]}


def train(cfg_path: str) -> None:
    import torch
    from datasets import Dataset  # type: ignore
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training  # type: ignore
    from transformers import (  # type: ignore
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    job = normalize_job(json.loads(Path(cfg_path).read_text(encoding="utf-8")))
    set_seed(job["seed"])
    tok = AutoTokenizer.from_pretrained(job["base_model"])
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    if job.get("require_gpu") and not torch.cuda.is_available():
        raise RuntimeError("this training job requires CUDA")
    kwargs: dict = {"torch_dtype": torch.bfloat16 if bf16 else torch.float16 if torch.cuda.is_available() else torch.float32}
    if job["method"] == "qlora":
        from transformers import BitsAndBytesConfig  # type: ignore

        kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                           bnb_4bit_compute_dtype=torch.bfloat16 if bf16 else torch.float32)
        kwargs["device_map"] = {"": 0} if job.get("require_gpu") else "auto"
    model = AutoModelForCausalLM.from_pretrained(job["base_model"], **kwargs)
    if job["method"] == "qlora":
        model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(r=job["r"], lora_alpha=job["alpha"], lora_dropout=job["dropout"],
                                             target_modules=job["target_modules"], task_type="CAUSAL_LM"))
    # GradScaler cannot unscale FP16 gradients. Promote only trainable weights.
    if torch.cuda.is_available() and not bf16:
        for parameter in model.parameters():
            if parameter.requires_grad and parameter.dtype == torch.float16:
                parameter.data = parameter.data.float()
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    targets = model.peft_config["default"].target_modules
    effective_targets = targets if isinstance(targets, str) else sorted(targets)
    model.config.use_cache = False
    model.enable_input_require_grads()

    data = Dataset.from_generator(message_rows, gen_kwargs={"path": job["dataset"],
                                  "content_hash": sha256(Path(job["dataset"]))})

    def encode(example):
        return encode_response(tok, example["messages"], job["max_seq_length"])

    data = data.map(encode, remove_columns=data.column_names)
    valid = None
    if job.get("validation"):
        valid = Dataset.from_generator(message_rows, gen_kwargs={"path": job["validation"],
                                       "content_hash": sha256(Path(job["validation"]))})
        valid = valid.map(encode, remove_columns=valid.column_names)
    trainer = Trainer(
        model=model,
        train_dataset=data,
        eval_dataset=valid,
        data_collator=DataCollatorForSeq2Seq(tok, label_pad_token_id=-100),
        args=TrainingArguments(output_dir=job["output_dir"], num_train_epochs=job["epochs"],
                               max_steps=job.get("max_steps", -1),
                               warmup_steps=job.get("warmup_steps", math.ceil(job.get("warmup_ratio", 0.0) *
                                   (job["max_steps"] if job.get("max_steps", -1) > 0 else
                                    math.ceil(len(data) / job["batch_size"] / job["gradient_accumulation"]) * job["epochs"]))),
                               max_grad_norm=job.get("max_grad_norm", 1.0),
                               lr_scheduler_type=job.get("lr_scheduler_type", "linear"),
                               per_device_train_batch_size=job["batch_size"],
                               per_device_eval_batch_size=job.get("eval_batch_size", job["batch_size"]),
                               gradient_accumulation_steps=job["gradient_accumulation"],
                               learning_rate=job["learning_rate"], logging_steps=10, save_strategy="epoch",
                               eval_strategy="epoch" if valid is not None and job.get("select_best") else "no",
                               load_best_model_at_end=bool(valid is not None and job.get("select_best")),
                               metric_for_best_model="eval_loss", greater_is_better=False,
                               save_total_limit=2,
                               bf16=bf16, fp16=torch.cuda.is_available() and not bf16,
                               seed=job["seed"], gradient_checkpointing=True,
                               report_to=[]),
    )
    if job.get("require_gpu") and any(p.device.type != "cuda" for p in model.parameters()):
        raise RuntimeError("training parameters were not placed entirely on CUDA")
    result = trainer.train(resume_from_checkpoint=job.get("resume_from_checkpoint"))
    metrics = dict(result.metrics)
    metrics.update(device="cuda" if torch.cuda.is_available() else "cpu",
                   trainable_parameters=trainable,
                   total_parameters=sum(p.numel() for p in model.parameters()),
                   target_modules=effective_targets,
                   trainable_dtypes=sorted({str(p.dtype) for p in model.parameters() if p.requires_grad}),
                   best_model_checkpoint=trainer.state.best_model_checkpoint,
                   best_metric=trainer.state.best_metric,
                   final_global_step=trainer.state.global_step,
                   parameter_devices=sorted({str(p.device) for p in model.parameters()}),
                   gpu_name=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                   peak_allocated_bytes=torch.cuda.max_memory_allocated() if torch.cuda.is_available() else 0)
    if valid is not None:
        metrics.update(trainer.evaluate())
    Path(job["output_dir"]).mkdir(parents=True, exist_ok=True)
    (Path(job["output_dir"]) / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    model.save_pretrained(job["output_dir"])
    tok.save_pretrained(job["output_dir"])


def merge(base: str, adapter: str, output: str) -> None:
    from peft import PeftModel  # type: ignore
    from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

    model = AutoModelForCausalLM.from_pretrained(base, torch_dtype="auto")
    base_dtype = str(model.dtype)
    model = PeftModel.from_pretrained(model, adapter).merge_and_unload()
    model.save_pretrained(output, safe_serialization=True)
    AutoTokenizer.from_pretrained(base).save_pretrained(output)
    (Path(output)/"merge-metrics.json").write_text(json.dumps({"base_dtype": base_dtype,
        "merged_dtype": str(model.dtype), "dtype_policy": "preserve-base-auto"},indent=2),encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] == "--merge":
        merge(*sys.argv[2:5])
    else:
        train(sys.argv[1])
