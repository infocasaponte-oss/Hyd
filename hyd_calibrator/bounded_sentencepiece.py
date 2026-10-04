"""Count BPE tokens in bounded word-aligned spans after exactly one normalization."""
# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import sentencepiece as spm
from sentencepiece import sentencepiece_model_pb2 as pb


class BoundedSentencePiece:
    def __init__(self, model, *, span_chars=16_384):
        self.original = spm.SentencePieceProcessor(model_file=str(model))
        self.span_chars = span_chars
        proto = pb.ModelProto()
        proto.ParseFromString(model.read_bytes())
        self.supported = (proto.trainer_spec.model_type == pb.TrainerSpec.BPE
                          and proto.normalizer_spec.escape_whitespaces
                          and any(p.piece == "▁" for p in proto.pieces)
                          and not any("▁" in p.piece.lstrip("▁") for p in proto.pieces))
        # Vocabulary/IDs/scores remain identical. Input is already normalized by the original.
        proto.normalizer_spec.name = "identity"
        proto.normalizer_spec.precompiled_charsmap = b""
        proto.normalizer_spec.add_dummy_prefix = False
        proto.normalizer_spec.remove_extra_whitespaces = False
        proto.normalizer_spec.escape_whitespaces = False
        self.pre_normalized = spm.SentencePieceProcessor(model_proto=proto.SerializeToString())

    def spans(self, text):
        normalized = self.original.normalize(text)
        position = 0
        while position < len(normalized):
            end = min(position + self.span_chars, len(normalized))
            if end < len(normalized):
                boundary = normalized.rfind("▁", position + 1, end)
                while boundary > position and normalized[boundary - 1] == "▁":
                    boundary -= 1
                if boundary <= position:
                    raise ValueError("normalized word/whitespace span exceeds safe tokenization budget")
                end = boundary
            yield normalized[position:end]
            position = end

    def count(self, text, threads):
        if len(text) <= self.span_chars:
            return len(self.original.encode(text, out_type=int))
        if not self.supported:
            raise ValueError("large records require a BPE vocabulary without pieces spanning word boundaries")
        total, batch = 0, []
        for span in self.spans(text):
            batch.append(span)
            if len(batch) == 16:
                total += sum(len(ids) for ids in self.pre_normalized.encode(batch, out_type=int, num_threads=threads))
                batch = []
        if batch:
            total += sum(len(ids) for ids in self.pre_normalized.encode(batch, out_type=int, num_threads=threads))
        return total

    def encode(self, texts, *, out_type=int, num_threads=2):
        if out_type is not int:
            raise ValueError("bounded census exposes token counts only")
        return [range(self.count(text, num_threads)) for text in texts]

    def bos_id(self):
        return self.original.bos_id()

    def eos_id(self):
        return self.original.eos_id()

    def vocab_size(self):
        return self.original.vocab_size()
