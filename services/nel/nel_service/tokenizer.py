"""Text to token ids for the BELA context encoder (XLM-R sentencepiece).

Mirrors the tokenization the released checkpoints were trained with: fairseq ids (sentencepiece
id plus one, unknown mapped to 3), beginning and end markers added by the caller, and character
boundaries of every piece so predicted token spans can be mapped back to character offsets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import sentencepiece as spm

BOS_ID, PAD_ID, EOS_ID, UNK_ID = 0, 1, 2, 3
MAX_SEQ_LEN = 256


@dataclass(frozen=True)
class Encoded:
    token_ids: list[int]  # includes BOS and EOS
    boundaries: list[tuple[int, int]]  # character start and end per piece (without BOS and EOS)


class Tokenizer:
    def __init__(self, model_path: str | Path, max_seq_len: int = MAX_SEQ_LEN) -> None:
        self.processor = spm.SentencePieceProcessor(model_file=str(model_path))
        self.max_seq_len = max_seq_len

    def encode(self, text: str) -> Encoded:
        proto = self.processor.encode(text, return_type="proto")
        leading_whitespace = len(text) - len(text.lstrip())
        ids = [BOS_ID]
        boundaries: list[tuple[int, int]] = []
        offset = 0
        for index, piece in enumerate(proto.pieces):
            token_id = piece.id + 1 if piece.id != 0 else UNK_ID
            length = len(piece.surface) + (leading_whitespace if index == 0 else 0)
            ids.append(token_id)
            boundaries.append((offset, offset + length))
            offset += length
            if index == self.max_seq_len - 3:
                break
        ids.append(EOS_ID)
        return Encoded(ids, boundaries)

    def char_span(self, encoded: Encoded, start_token: int, end_token: int, text: str) -> tuple[int, int]:
        """Character span for an inclusive token span, where token 1 is the first piece."""
        start = encoded.boundaries[start_token - 1][0]
        end = encoded.boundaries[end_token - 1][1]
        while start < end and text[start].isspace():
            start += 1
        return start, end
