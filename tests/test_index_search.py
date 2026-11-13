import json
import os
import shutil

from comitra.core import export, search, stats
from comitra.core.query import parse
from comitra.core.search import SearchOptions
from comitra.core.service import update_index, update_known_repos


def rmtree(path):
    """shutil.rmtree that also removes git's read-only object files on Windows."""
    import stat

    def onerror(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=onerror)


def run(conn, settings, **kw):
    return update_index(conn, settings, **kw)


def find(conn, text, **opts):
    res = search.search(conn, parse(text), SearchOptions(**opts), resolver=search.BranchResolver())
    rows = search.fetch_rows(conn, res.ids)
    return [rows[i]["subject"] for i in res.ids], res


def test_basic_index_and_turkish_search(conn, settings, make_repo):
    r = make_repo("billing-api")
    r.commit("Ödeme hatası düzeltildi")
    r.commit("İade akışı eklendi")
    r.commit("WIP: refactor")
    rep = run(conn, settings)
    assert rep.summary.count("updated") == 1
    assert find(conn, "odeme")[0] == ["Ödeme hatası düzeltildi"]
    assert find(conn, "iade")[0] == ["İade akışı eklendi"]
    assert find(conn, "IADE")[0] == ["İade akışı eklendi"]
    assert find(conn, '"ödeme hatası"')[0] == ["Ödeme hatası düzeltildi"]
    assert find(conn, "hata*")[0] == ["Ödeme hatası düzeltildi"]
    assert set(find(conn, "-wip")[0]) == {"Ödeme hatası düzeltildi", "İade akışı eklendi"}
    assert find(conn, "repo:billing -wip -iade")[0] == ["Ödeme hatası düzeltildi"]
    assert find(conn, "repo:nope")[0] == []


def test_unchanged_repo_is_skipped_and_old_dated_commit_found(conn, settings, make_repo):
    r = make_repo()
    r.commit("first", date="2026-10-15T10:00:00+03:00")
    run(conn, settings)
    rep = run(conn, settings)
    assert rep.summary.count("unchanged") == 1
    # A commit with an *older* date than everything indexed must still be found.
    r.commit("old dated", date="2020-01-01T10:00:00+00:00")
    rep = run(conn, settings)
    assert rep.summary.new_commits == 1
    assert find(conn, "old")[0] == ["old dated"]


def test_fast_forward_merge_updates_branch_membership(conn, settings, make_repo):
    r = make_repo()
    r.commit("base")
    r.git("checkout", "-q", "-b", "feature/x")
    r.commit("feature work")
    r.git("checkout", "-q", "main")
    run(conn, settings)
    assert find(conn, "branch:main")[0] == ["base"]
    assert set(find(conn, "branch:feature/*")[0]) == {"base", "feature work"}
    r.git("merge", "-q", "--ff-only", "feature/x")
    rep = run(conn, settings)
    assert rep.summary.new_commits == 0  # no new commits, but membership changed
    assert set(find(conn, "branch:main")[0]) == {"base", "feature work"}


def test_force_push_marks_commits_unreachable(conn, settings, make_repo):
    r = make_repo()
    r.commit("keep")
    r.commit("to be rewritten")
    run(conn, settings)
    r.git("reset", "-q", "--hard", "HEAD~1")
    r.commit("rewritten")
    rep = run(conn, settings)
    assert rep.summary.results[0].unreachable == 1
    assert set(find(conn, "")[0]) == {"keep", "rewritten"}
    assert find(conn, "unreachable:only")[0] == ["to be rewritten"]
    assert len(find(conn, "unreachable:include")[0]) == 3
    # The commit comes back if a branch points at it again.
    old = r.git("rev-parse", "HEAD@{2}").strip()
    r.git("branch", "restore", old)
    run(conn, settings)
    assert find(conn, "unreachable:only")[0] == []


def test_keep_unreachable_disabled_deletes(conn, settings, make_repo):
    settings.keep_unreachable = False
    r = make_repo()
    r.commit("a")
    r.git("checkout", "-q", "-b", "tmp")
    r.commit("b")
    run(conn, settings)
    r.git("checkout", "-q", "main")
    r.git("branch", "-q", "-D", "tmp")
    run(conn, settings)
    assert find(conn, "unreachable:include")[0] == ["a"]


def test_garbage_collected_tip_triggers_full_pass(conn, settings, make_repo):
    r = make_repo()
    r.commit("a")
    run(conn, settings)
    conn.execute("UPDATE refs SET target='0000000000000000000000000000000000000001'")
    conn.execute("UPDATE repos SET refs_fingerprint='x'")
    r.commit("b")
    rep = run(conn, settings)
    assert rep.summary.results[0].status == "updated"
    assert set(find(conn, "")[0]) == {"a", "b"}


def test_worktree_submodule_bare(conn, settings, make_repo, tmp_path):
    main = make_repo("main")
    main.commit("main commit")
    main.git("worktree", "add", "-q", str(tmp_path / "work" / "wt"), "-b", "wt-branch")
    bare_src = make_repo("src")
    bare_src.commit("bare commit")
    shutil.move(bare_src.path, str(tmp_path / "elsewhere"))
    main.git("clone", "-q", "--bare", str(tmp_path / "elsewhere"), str(tmp_path / "work" / "srv.git"))
    rep = run(conn, settings)
    names = sorted(r.name for r in rep.summary.results)
    assert names == ["main", "srv"]  # worktree de-duplicated, bare repo found
    assert set(find(conn, "commit")[0]) == {"main commit", "bare commit"}


def test_moved_repo_keeps_identity(conn, settings, make_repo, tmp_path):
    r = make_repo("proj")
    r.commit("hello")
    run(conn, settings)
    rid = conn.execute("SELECT id FROM repos").fetchone()[0]
    shutil.move(r.path, str(tmp_path / "work" / "proj-renamed"))
    rep = run(conn, settings)
    rows = conn.execute("SELECT id, name FROM repos").fetchall()
    assert [(x[0], x[1]) for x in rows] == [(rid, "proj-renamed")]
    assert rep.summary.new_commits == 0


def test_authors_coauthors_files_hash(conn, settings, make_repo):
    r = make_repo()
    h1 = r.commit("auth fix\n\nCo-authored-by: Ayşe Kaya <ayse@firma.com>", files={"src/auth/login.py": "x"})
    r.commit("docs", author=("Mehmet Öz", "mehmet@firma.com"), files={"docs/ödeme notu.md": "y"})
    run(conn, settings)
    assert find(conn, "author:ayse")[0] == ["auth fix"]
    assert find(conn, "author:mehmet")[0] == ["docs"]
    assert find(conn, "author:AHMET")[0] == ["auth fix"]
    assert find(conn, "file:*.py")[0] == ["auth fix"]
    assert find(conn, "file:src/auth/")[0] == ["auth fix"]
    assert find(conn, "file:odeme")[0] == ["docs"]
    assert find(conn, f"hash:{h1[:7]}")[0] == ["auth fix"]
    assert find(conn, h1[:9])[0] == ["auth fix"]


def test_merge_time_filters_and_grouping(conn, settings, make_repo):
    r = make_repo()
    r.commit("morning", date="2026-11-13T09:30:00+03:00")  # Friday
    r.git("checkout", "-q", "-b", "side")
    r.commit("night", date="2026-11-14T23:10:00+03:00")    # Saturday
    r.git("checkout", "-q", "main")
    r.git("merge", "-q", "--no-ff", "-m", "Merge side", "side",
          env={"GIT_AUTHOR_DATE": "2026-11-15T12:00:00+03:00", "GIT_COMMITTER_DATE": "2026-11-15T12:00:00+03:00"})
    run(conn, settings)
    assert find(conn, "merge:only")[0] == ["Merge side"]
    assert "Merge side" not in find(conn, "merge:hide")[0]
    assert find(conn, "hour:09-12")[0] == ["morning"]
    assert find(conn, "hour:22-06")[0] == ["night"]
    assert find(conn, "day:cuma")[0] == ["morning"]
    assert find(conn, "day:weekend merge:hide")[0] == ["night"]
    assert find(conn, "sort:oldest")[0][0] == "morning"
    subjects, res = find(conn, "", group_by="day")
    assert len(set(res.groups)) == 3


def test_update_known_repos_and_export_stats(conn, settings, make_repo, tmp_path):
    r = make_repo()
    r.commit("one")
    run(conn, settings)
    r.commit("two")
    rep = update_known_repos(conn, settings)
    assert rep.summary.new_commits == 1
    _, res = find(conn, "")
    out_csv = tmp_path / "out.csv"
    out_json = tmp_path / "out.json"
    assert export.export_csv(conn, res.ids, str(out_csv)) == 2
    assert export.export_json(conn, res.ids, str(out_json)) == 2
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data[0]["subject"] == "two"
    st = stats.compute(conn)
    assert st.total_commits == 2 and st.total_repos == 1


def test_missing_repo_marked(conn, settings, make_repo):
    r = make_repo()
    r.commit("x")
    run(conn, settings)
    rmtree(r.path)
    run(conn, settings)
    assert conn.execute("SELECT status FROM repos").fetchone()[0] == "missing"
    # Data stays searchable.
    assert find(conn, "x")[0] == ["x"]


def test_fetch_from_local_remote(conn, settings, make_repo, tmp_path):
    upstream = make_repo("upstream")
    upstream.commit("up1")
    clone_path = tmp_path / "work" / "clone"
    upstream.git("clone", "-q", upstream.path, str(clone_path))
    settings.fetch_before_scan = True
    run(conn, settings)
    upstream.commit("up2 from teammate", date="2019-05-05T10:00:00+00:00")
    rep = run(conn, settings)
    clone_res = [x for x in rep.summary.results if x.name == "clone"][0]
    assert clone_res.fetch is not None and clone_res.fetch.ok
    assert len([s for s in find(conn, "repo:clone teammate")[0]]) == 1


def test_fetch_failure_keeps_indexing(conn, settings, make_repo):
    r = make_repo()
    r.commit("local")
    r.git("remote", "add", "origin", os.path.join(r.path, "does-not-exist"))
    settings.fetch_before_scan = True
    rep = run(conn, settings)
    res = rep.summary.results[0]
    assert res.fetch is not None and not res.fetch.ok
    assert res.status == "updated"
    assert find(conn, "local")[0] == ["local"]
