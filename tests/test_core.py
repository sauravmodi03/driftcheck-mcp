import os, socket, tempfile, unittest
from driftcheck.core import extract, verify, OK, DRIFT


class ExtractTests(unittest.TestCase):
    def test_paths_ports_units(self):
        md = ("Run `~/.local/bin/hermes` and see http://127.0.0.1:3000.\n"
              "Timer `pod-backup.timer` runs daily.\n")
        kinds = {(c.kind, c.value) for c in extract(md)}
        self.assertIn(("path", "~/.local/bin/hermes"), kinds)
        self.assertIn(("port", "127.0.0.1:3000"), kinds)
        self.assertIn(("unit", "pod-backup.timer"), kinds)

    def test_bare_host_port_but_not_url_dupes(self):
        cs = extract("git SSH 127.0.0.1:2222 and http://127.0.0.1:3000/x")
        self.assertEqual(sorted(c.value for c in cs if c.kind == "port"),
                         ["127.0.0.1:2222", "127.0.0.1:3000"])

    def test_ignores_code_fences_placeholders_and_remote_urls(self):
        md = "```\n`/etc/passwd`\n```\n`/tmp/<name>` https://example.com:443 `/tmp/*`\n"
        self.assertEqual(extract(md), [])

    def test_line_numbers_and_dedup(self):
        cs = extract("a\n`/tmp`\n`/tmp`\n")
        self.assertEqual([(c.value, c.line) for c in cs], [("/tmp", 2)])


class RepoTests(unittest.TestCase):
    def test_extract_remote_and_url(self):
        md = ("git remote `forge:me/app.git` and http://127.0.0.1:3000/me/lib/pulls "
              "api http://127.0.0.1:3000/api/v1/repos/x/y")
        repos = sorted(c.value for c in extract(md) if c.kind == "repo")
        self.assertEqual(repos, ["me/app", "me/lib"])

    def test_scope_applies_to_repo_claims(self):
        c = extract("`forge:me/app` <!-- driftcheck: scope=mac -->")[0]
        self.assertEqual((c.kind, c.scope), ("repo", "mac"))

    def test_unreachable_forgejo_is_unverifiable_not_drift(self):
        import os
        from driftcheck import core
        old = os.environ.get("FORGEJO_URL"); os.environ["FORGEJO_URL"] = "http://127.0.0.1:1"
        try:
            self.assertEqual(core._check_repo("me/app")[0], core.UNKNOWN)
        finally:
            os.environ.pop("FORGEJO_URL") if old is None else os.environ.update(FORGEJO_URL=old)

    def test_collect_expands_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "a.md"), "w").close(); open(os.path.join(d, "b.txt"), "w").close()
            from driftcheck.core import collect
            self.assertEqual([os.path.basename(x) for x in collect([d])], ["a.md"])


class PathHeuristicTests(unittest.TestCase):
    def test_route_like_path_is_unverifiable_but_missing_file_is_drift(self):
        from driftcheck.core import UNKNOWN
        res = {r.claim.value: r.status for r in verify(extract("`/user/tokens/verify` `/tmp/definitely-missing-x`"))}
        self.assertEqual(res, {"/user/tokens/verify": UNKNOWN, "/tmp/definitely-missing-x": DRIFT})


class MarkerTests(unittest.TestCase):
    def test_ignore_same_line_and_next_line(self):
        md = ("`/tmp/nope-driftcheck/a` <!-- driftcheck: ignore -->\n"
              "<!-- driftcheck: ignore -->\n`/tmp/nope-driftcheck/b`\n`/tmp/nope-driftcheck/c`\n")
        self.assertEqual([c.value for c in extract(md)], ["/tmp/nope-driftcheck/c"])

    def test_scope_skipped_unless_active(self):
        md = "`/tmp/nope-driftcheck/mac` <!-- driftcheck: scope=mac -->\n`/tmp/nope-driftcheck/pod`\n"
        by = {r.claim.value: r.status for r in verify(extract(md))}
        self.assertEqual(by, {"/tmp/nope-driftcheck/mac": "skipped", "/tmp/nope-driftcheck/pod": DRIFT})
        by = {r.claim.value: r.status for r in verify(extract(md), "mac")}
        self.assertEqual(by["/tmp/nope-driftcheck/mac"], DRIFT)

    def test_scope_applies_to_all_claim_kinds(self):
        c = extract("127.0.0.1:12222 <!-- driftcheck: scope=mac -->")[0]
        self.assertEqual((c.kind, c.scope), ("port", "mac"))


class VerifyTests(unittest.TestCase):
    def test_path(self):
        with tempfile.TemporaryDirectory() as d:
            res = verify(extract(f"`{d}` and `{d}/missing`"))
        self.assertEqual([r.status for r in res], [OK, DRIFT])

    def test_port(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)
        live = s.getsockname()[1]
        dead = socket.socket(); dead.bind(("127.0.0.1", 0)); dp = dead.getsockname()[1]; dead.close()
        res = verify(extract(f"http://127.0.0.1:{live} http://127.0.0.1:{dp}"))
        s.close()
        self.assertEqual([r.status for r in res], [OK, DRIFT])


if __name__ == "__main__":
    unittest.main()
