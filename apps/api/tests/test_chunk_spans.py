from meridian.linking.chunk import make_chunks
from meridian.linking.spans import capitalized_spans


def test_short_text_is_one_chunk() -> None:
    chunks = make_chunks("A fire broke out in Dayton.", "en", max_chars=700)
    assert len(chunks) == 1 and chunks[0].start == 0


def test_long_text_is_chunked_with_overlap_and_offsets() -> None:
    sentence = "The warehouse in Springfield caught fire on Monday night. "
    text = sentence * 40
    chunks = make_chunks(text, "en", max_chars=300, overlap_sentences=1)
    assert len(chunks) > 3
    for chunk in chunks:
        assert len(chunk.text) <= 300 + len(sentence)
        assert text[chunk.start : chunk.start + len(chunk.text)] == chunk.text
    # consecutive chunks overlap by one sentence
    assert chunks[1].start < chunks[0].start + len(chunks[0].text)
    assert chunks[0].start == 0 and chunks[-1].start + len(chunks[-1].text) >= len(text.rstrip())


def test_very_long_sentence_is_cut_at_whitespace() -> None:
    text = "word " * 400
    chunks = make_chunks(text, "en", max_chars=200)
    assert all(len(c.text) <= 205 for c in chunks)
    assert all(not c.text.startswith("ord") for c in chunks)


def test_capitalized_spans_find_names_with_connectors() -> None:
    text = "A fire at the Port of Rotterdam spread, said Mayor Bob Smith of Dayton, Ohio on Tuesday."
    found = {s.text for s in capitalized_spans(text)}
    assert "Port of Rotterdam" in found and "Rotterdam" in found
    assert "Dayton" in found and "Ohio" in found
    assert "Tuesday" in found  # callers filter by gazetteer membership
    assert "fire" not in found and "on" not in found


def test_non_latin_cased_scripts_are_supported() -> None:
    found = {s.text for s in capitalized_spans("Пожар в Москве вспыхнул утром. Мэр Москвы заявил.")}
    assert "Москве" in found and "Москвы" in found


def test_trailing_connector_is_trimmed() -> None:
    assert all(not s.text.lower().endswith((" of", " de")) for s in capitalized_spans("They live in Paris de"))
