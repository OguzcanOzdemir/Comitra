from datetime import date

from comitra.core.query import DateFilter, Query, Term, parse, parse_hours


def test_full_example():
    q = parse('author:alice repo:billing branch:feature/* after:2026-10-01 before:2026-11-01 payment')
    assert q.authors == ["alice"]
    assert q.repos == ["billing"]
    assert q.branches == ["feature/*"]
    assert q.after == date(2026, 10, 1)
    assert q.before == date(2026, 11, 1)
    assert [t.text for t in q.terms] == ["payment"]


def test_text_terms():
    q = parse('"payment error" -wip login* -"work in progress"')
    assert q.terms[0].phrase and q.terms[0].text == "payment error"
    assert q.terms[1].negated and q.terms[1].text == "wip"
    assert q.terms[2].prefix and q.terms[2].bare == "login"
    assert q.terms[3].negated and q.terms[3].phrase


def test_multi_values_and_quotes():
    q = parse('author:"Alice Smith",bob@example.com a:carol')
    assert q.authors == ["Alice Smith", "bob@example.com", "carol"]


def test_aliases_and_presets():
    q = parse("d:today b:main weekday:fri,saturday time:09-12 merge:hide")
    assert q.date.preset == "today"
    assert q.branches == ["main"]
    assert q.days == [4, 5]
    assert q.hours == (9, 12)
    assert q.merge == "hide"


def test_date_values():
    assert parse("date:2026-10-01..2026-10-31").date == DateFilter(start=date(2026, 10, 1), end=date(2026, 10, 31))
    assert parse("date:2026-11-10").date.bounds() == (date(2026, 11, 10), date(2026, 11, 11))
    assert parse("date:2026-02").date.end == date(2026, 2, 28)
    assert parse("date:7d").date.bounds(date(2026, 11, 13)) == (date(2026, 11, 7), date(2026, 11, 14))
    assert parse("date:month").date.bounds(date(2026, 11, 13))[0] == date(2026, 11, 1)


def test_invalid_filter_reported():
    q = parse("date:tomorrow foo")
    assert q.errors == ["date:tomorrow"]
    assert [t.text for t in q.terms] == ["foo"]


def test_unknown_key_is_text():
    q = parse("fix:login http://x")
    assert [t.text for t in q.terms] == ["fix:login", "http://x"]


def test_roundtrip():
    s = 'author:alice,"Bob K" repo:api branch:feature/* hash:a1b2c3d file:*.py date:2026-10-01..2026-10-31 hour:22-06 day:fri,sat merge:only unreachable:include sort:oldest "payment error" -wip login*'
    q = parse(s)
    assert parse(q.to_string()).to_string() == q.to_string()
    assert q.to_string() == s


def test_hours():
    assert parse_hours("9") == (9, 10)
    assert parse_hours("09:00-12:30") == (9, 13)
    assert parse_hours("22-06") == (22, 6)
    assert parse_hours("25") is None


def test_effective_sort():
    assert Query().effective_sort() == "newest"
    assert Query(terms=[Term("x")]).effective_sort() == "relevance"
    assert Query(sort="relevance").effective_sort() == "newest"
