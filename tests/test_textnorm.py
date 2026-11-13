from comitra.core.textnorm import highlight_html, highlight_spans, normalize, tokens


def test_dotted_and_dotless_i_fold_together():
    # Unicode lower() turns "İ" into two code points; search must treat all
    # i variants as the same letter.
    assert normalize("İstanbul") == normalize("istanbul") == normalize("ISTANBUL") == "istanbul"
    assert normalize("ı") == "i"
    assert normalize("INFO") == "info"


def test_diacritics_removed():
    assert normalize("Café Crème") == "cafe creme"
    assert normalize("naïve résumé") == "naive resume"
    assert normalize("Straße") == "strase"
    assert normalize("Ångström Øre") == "angstrom ore"


def test_length_preserving():
    for s in ["İstanbul", "Straße", "ǅemal", "çğş", "naïve café", "日本語"]:
        assert len(normalize(s)) == len(s)


def test_tokens():
    assert tokens(normalize("fix: JIRA-1234 snake_case")) == ["fix", "jira", "1234", "snake_case"]


def test_highlight_maps_to_original():
    text = "Café PAYMENTS fixed"
    spans = highlight_spans(text, [("cafe", False), ("payment", True)])
    assert [text[a:b] for a, b in spans] == ["Café", "PAYMENTS"]
    html = highlight_html("a <b> café", [("cafe", False)], "[", "]")
    assert html == "a &lt;b&gt; [café]"
