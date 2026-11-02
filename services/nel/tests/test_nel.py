import numpy as np
import pytest
import torch

from nel_service import index as index_module
from nel_service.linker import resolve_overlaps
from nel_service.model import span_scores


def test_span_scores_picks_the_marked_span() -> None:
    logits = torch.full((8, 3), -5.0)  # BOS, six pieces, EOS
    logits[3, 0] = 6.0  # start at piece 3
    logits[4, 1] = 6.0  # end at piece 4
    logits[3:5, 2] = 4.0  # inside the span
    scores, starts, ends = span_scores(logits, valid_tokens=6)
    assert (int(starts[0]), int(ends[0])) == (3, 4)
    assert float(torch.sigmoid(scores[0])) > 0.9
    assert float(torch.sigmoid(scores[1])) < float(torch.sigmoid(scores[0]))


def test_span_scores_respect_length_limit_and_bounds() -> None:
    logits = torch.zeros((30, 3))
    _, starts, ends = span_scores(logits, valid_tokens=28, max_len=4, top_k=500)
    assert int((ends - starts).max()) <= 3
    assert int(starts.min()) >= 1 and int(ends.max()) <= 28


def test_overlap_resolution_keeps_best_and_longest() -> None:
    kept = resolve_overlaps([(0.9, 3, 4), (0.8, 3, 3), (0.8, 4, 4), (0.5, 8, 9), (0.5, 9, 9)])
    assert kept == [(0.9, 3, 4), (0.5, 8, 9)]
    assert resolve_overlaps([(0.6, 2, 2), (0.6, 2, 3)]) == [(0.6, 2, 3)]


def test_qid_parsing() -> None:
    assert index_module.qid_to_int("Q42") == 42
    assert index_module.qid_to_int("P31") == -1
    assert index_module.qid_to_int("Qabc") == -1


def test_device_matrix_search_and_gather_across_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(index_module, "CHUNK_ROWS", 4)
    monkeypatch.setattr(index_module, "DIM", 3)
    monkeypatch.setattr(index_module, "DIM", index_module.DIM)
    rng = np.random.default_rng(0)
    data = rng.normal(size=(11, index_module.DIM)).astype(np.float16)
    matrix = index_module.DeviceMatrix(data, torch.device("cpu"))
    assert len(matrix.chunks) == 3
    query = torch.from_numpy(data[[9]].copy())
    scores, rows = matrix.search(query, 3)
    expected = np.argsort(-(data.astype(np.float32) @ data[9].astype(np.float32)))[:3]
    assert rows[0].tolist() == expected.tolist()
    gathered = matrix.gather(torch.tensor([[0, 10], [5, 4]]))
    assert gathered.shape == (2, 2, 3)
    assert np.allclose(gathered[0, 1].numpy(), data[10])
    assert np.allclose(gathered[1, 0].numpy(), data[5])


def test_tokenizer_matches_fairseq_ids_and_offsets() -> None:
    pytest.importorskip("sentencepiece")
    try:
        from huggingface_hub import hf_hub_download

        model = hf_hub_download("FacebookAI/xlm-roberta-large", "sentencepiece.bpe.model")
    except Exception as exc:  # offline
        pytest.skip(f"tokenizer model unavailable: {exc}")
    from nel_service.tokenizer import BOS_ID, EOS_ID, Tokenizer

    tokenizer = Tokenizer(model)
    text = "  Fire at the Port of Rotterdam."
    encoded = tokenizer.encode(text)
    assert encoded.token_ids[0] == BOS_ID and encoded.token_ids[-1] == EOS_ID
    assert len(encoded.boundaries) == len(encoded.token_ids) - 2
    assert encoded.boundaries[-1][1] == len(text)  # pieces cover the whole text
    assert all(a[1] == b[0] for a, b in zip(encoded.boundaries, encoded.boundaries[1:], strict=False))
    last = len(encoded.boundaries)
    assert text[slice(*tokenizer.char_span(encoded, last, last, text))] == "."
    first = text[slice(*tokenizer.char_span(encoded, 1, 1, text))]
    assert first.startswith("Fi")  # leading whitespace is skipped
    whole = text[slice(*tokenizer.char_span(encoded, 1, last, text))]
    assert whole == text.strip()
