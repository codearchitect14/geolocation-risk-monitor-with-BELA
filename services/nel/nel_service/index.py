"""Entity embedding index: exact inner product search on the Apple GPU.

BELA's released index has 16.5 million entities with 300 dimensional vectors. The float32 file
is 19.8 GB, so it is converted once to float16 on disk (9.9 GB) and held on the device in chunks
of one million rows (a single tensor of this size would exceed 32 bit indexing on MPS).

Besides the full index, a compact index of the rows whose QID is a known place is kept. Searching
both lets the service report BELA's own top candidates and the best place candidates.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch

log = logging.getLogger("nel.index")

DIM = 300
CHUNK_ROWS = 1_000_000


def qid_to_int(qid: str) -> int:
    return int(qid[1:]) if qid.startswith("Q") and qid[1:].isdigit() else -1


def read_ids(path: Path) -> np.ndarray:
    """QIDs of the index rows as integers (row i of the embedding file is line i)."""
    with path.open(encoding="utf-8") as handle:
        return np.fromiter((qid_to_int(line.strip()) for line in handle), dtype=np.int64)


def convert_embeddings(source: Path, target: Path, chunk: int = 500_000) -> tuple[int, int]:
    """Convert BELA's float32 embeddings.pt to a float16 .npy file, streaming through a memory map."""
    tensor = torch.load(str(source), map_location="cpu", mmap=True, weights_only=True)
    rows, dim = tensor.shape
    out = np.lib.format.open_memmap(str(target), mode="w+", dtype=np.float16, shape=(rows, dim))
    for start in range(0, rows, chunk):
        out[start : start + chunk] = tensor[start : start + chunk].to(torch.float16).numpy()
        if (start // chunk) % 10 == 0:
            log.info("converted %d of %d rows", start, rows)
    out.flush()
    return rows, dim


class DeviceMatrix:
    """A (rows, DIM) float16 matrix stored as device chunks, with top-k search and row gather."""

    def __init__(self, array: np.ndarray, device: torch.device) -> None:
        self.rows = int(array.shape[0])
        self.device = device
        self.chunks = [
            torch.from_numpy(np.ascontiguousarray(array[start : start + CHUNK_ROWS])).to(device)
            for start in range(0, self.rows, CHUNK_ROWS)
        ]

    def search(self, queries: torch.Tensor, k: int) -> tuple[torch.Tensor, torch.Tensor]:
        """Top-k inner products. queries (M, DIM) float16 on the device. Returns (scores, rows)."""
        best_scores: list[torch.Tensor] = []
        best_rows: list[torch.Tensor] = []
        for index, chunk in enumerate(self.chunks):
            scores = queries @ chunk.T
            top_scores, top_rows = scores.topk(min(k, chunk.shape[0]), dim=1)
            best_scores.append(top_scores.float())
            best_rows.append(top_rows + index * CHUNK_ROWS)
        merged_scores = torch.cat(best_scores, dim=1)
        merged_rows = torch.cat(best_rows, dim=1)
        final_scores, order = merged_scores.topk(min(k, merged_scores.shape[1]), dim=1)
        return final_scores, merged_rows.gather(1, order)

    def gather(self, rows: torch.Tensor) -> torch.Tensor:
        """Vectors for row indices of any shape (…) → (…, DIM) float16."""
        flat = rows.reshape(-1)
        out = torch.empty((flat.numel(), DIM), dtype=torch.float16, device=self.device)
        for index, chunk in enumerate(self.chunks):
            mask = (flat // CHUNK_ROWS) == index
            if mask.any():
                out[mask] = chunk[flat[mask] - index * CHUNK_ROWS]
        return out.reshape(*rows.shape, DIM)


class EntityIndex:
    def __init__(self, embeddings_fp16: Path, ids_path: Path, place_qids: set[int], device: torch.device) -> None:
        self.device = device
        self.ids = read_ids(ids_path)
        array = np.load(str(embeddings_fp16), mmap_mode="r")
        if array.shape[0] != self.ids.shape[0]:
            raise ValueError(f"{array.shape[0]} embeddings but {self.ids.shape[0]} ids")
        log.info("loading %d vectors to %s", array.shape[0], device)
        self.full = DeviceMatrix(array, device)
        place_mask = np.isin(self.ids, np.fromiter(place_qids, dtype=np.int64))
        self.place_rows = np.flatnonzero(place_mask)
        log.info("%d index rows are known places", len(self.place_rows))
        self.places = DeviceMatrix(np.asarray(array[self.place_rows]), device)
        self.place_rows_device = torch.from_numpy(self.place_rows).to(device)

    def qid(self, row: int) -> str:
        return f"Q{int(self.ids[row])}"

    def place_row_to_global(self, rows: torch.Tensor) -> torch.Tensor:
        return self.place_rows_device[rows]

    _place_ids_sorted: np.ndarray

    def is_place(self, qid: str) -> bool:
        value = qid_to_int(qid)
        position = np.searchsorted(self.place_rows_ids_sorted, value)
        return bool(position < len(self.place_rows_ids_sorted) and self.place_rows_ids_sorted[position] == value)

    @property
    def place_rows_ids_sorted(self) -> np.ndarray:
        if not hasattr(self, "_place_ids_sorted"):
            self._place_ids_sorted = np.sort(self.ids[self.place_rows])
        return self._place_ids_sorted
