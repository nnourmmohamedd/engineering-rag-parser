from __future__ import annotations

from engineering_rag.databases.bm25.tokenizer import tokenize


class TestEngineeringIdentifiers:
    def test_p_and_id(self) -> None:
        tokens = tokenize("Review the P&ID before construction.")
        assert "p&id" in tokens
        assert "p" in tokens
        assert "id" in tokens

    def test_hyphenated_tag_number(self) -> None:
        tokens = tokenize("Check PT-101 reading.")
        assert "pt-101" in tokens
        assert "pt" in tokens
        assert "101" in tokens

    def test_underscore_tag_number(self) -> None:
        tokens = tokenize("Loop FT_203 is out of range.")
        assert "ft_203" in tokens
        assert "ft" in tokens
        assert "203" in tokens

    def test_range_with_unit(self) -> None:
        tokens = tokenize("Signal is 4-20 mA.")
        assert "4-20" in tokens
        assert "4" in tokens
        assert "20" in tokens
        assert "ma" in tokens

    def test_ampersand_acronym(self) -> None:
        tokens = tokenize("C&I engineering scope.")
        assert "c&i" in tokens
        assert "c" in tokens
        assert "i" in tokens

    def test_standard_with_number(self) -> None:
        tokens = tokenize("Comply with IEC 61511.")
        assert "iec" in tokens
        assert "61511" in tokens

    def test_isa_dotted_identifier(self) -> None:
        tokens = tokenize("Per ISA-5.1 symbols.")
        assert "isa-5.1" in tokens
        assert "isa" in tokens
        assert "5" in tokens
        assert "1" in tokens

    def test_sil_level(self) -> None:
        tokens = tokenize("This is SIL 2 rated.")
        assert "sil" in tokens
        assert "2" in tokens

    def test_feed_acronym(self) -> None:
        assert "feed" in tokenize("The FEED phase begins now.")

    def test_control_valve_phrase(self) -> None:
        tokens = tokenize("control valve sizing")
        assert "control" in tokens
        assert "valve" in tokens
        assert "sizing" in tokens

    def test_instrument_index_phrase(self) -> None:
        tokens = tokenize("instrument index")
        assert tokens == ["instrument", "index"]


class TestTokenizerProperties:
    def test_deterministic(self) -> None:
        text = "PT-101 and FT_203 measure flow per IEC 61511."
        assert tokenize(text) == tokenize(text)

    def test_case_normalization(self) -> None:
        assert tokenize("PT-101") == tokenize("pt-101")

    def test_unicode_normalization(self) -> None:
        import unicodedata

        composed = unicodedata.normalize("NFC", "café")
        decomposed = unicodedata.normalize("NFD", "café")
        assert tokenize(composed) == tokenize(decomposed)

    def test_empty_string(self) -> None:
        assert tokenize("") == []

    def test_whitespace_only(self) -> None:
        assert tokenize("   \n\t  ") == []

    def test_no_stopword_removal_preserves_negation(self) -> None:
        tokens = tokenize("This valve is not rated for this service.")
        assert "not" in tokens

    def test_punctuation_stripped_at_boundaries(self) -> None:
        tokens = tokenize("(see section 3.1), and also (4.2).")
        assert "3.1" in tokens or "3" in tokens
        assert all(not t.startswith("(") and not t.endswith(")") for t in tokens)

    def test_no_stemming(self) -> None:
        tokens = tokenize("instruments instrumentation")
        assert "instruments" in tokens
        assert "instrumentation" in tokens
        assert "instrument" not in tokens
