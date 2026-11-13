from comitra.core.textnorm import highlight_html, highlight_spans, normalize, tokens


def test_turkish_i_variants_fold_together():
    assert normalize("İade") == normalize("iade") == normalize("IADE") == "iade"
    assert normalize("ılık") == "ilik"
    assert normalize("INFO") == "info"


def test_diacritics_removed():
    assert normalize("Ödeme Hatası") == "odeme hatasi"
    assert normalize("çğşüö ÇĞŞÜÖ") == "cgsuo cgsuo"
    assert normalize("Straße") == "strase"


def test_length_preserving():
    for s in ["İstanbul", "Straße", "ǅemal", "çğş", "naïve café", "日本語"]:
        assert len(normalize(s)) == len(s)


def test_tokens():
    assert tokens(normalize("fix: JIRA-1234 snake_case")) == ["fix", "jira", "1234", "snake_case"]


def test_highlight_maps_to_original():
    text = "Ödeme HATASI düzeltildi"
    spans = highlight_spans(text, [("odeme", False), ("hata", True)])
    assert [text[a:b] for a, b in spans] == ["Ödeme", "HATASI"]
    html = highlight_html("a <b> ödeme", [("odeme", False)], "[", "]")
    assert html == "a &lt;b&gt; [ödeme]"
