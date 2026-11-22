import io, os, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from driftcheck import timer
from driftcheck.cli import main


class RenderTests(unittest.TestCase):
    def test_basic(self):
        svc, tmr = timer.render("dc", "*-*-* 04:10", ["/bin/driftcheck"], ["/a/CLAUDE.md"], "pod")
        self.assertIn("ExecStart=/bin/driftcheck --scope pod /a/CLAUDE.md\n", svc)
        self.assertIn("OnCalendar=*-*-* 04:10\nPersistent=true\n", tmr)
        self.assertIn("WantedBy=timers.target", tmr)

    def test_quotes_spaces_and_escapes_percent(self):
        svc, _ = timer.render("dc", "daily", ["/bin/dc"], ["/my docs/100%.md"], None)
        self.assertIn("'/my docs/100%%.md'", svc)

    def test_rejects_bad_name_and_control_chars(self):
        with self.assertRaises(ValueError):
            timer.render("../evil", "daily", ["/bin/dc"], ["/a"], None)
        with self.assertRaises(ValueError):
            timer.render("dc", "daily\nExecStart=/bin/rm", ["/bin/dc"], ["/a"], None)
        with self.assertRaises(ValueError):
            timer.render("dc", "daily", ["/bin/dc"], ["/a\nExecStart=x"], None)

    def test_no_persistent(self):
        _, tmr = timer.render("dc", "daily", ["/bin/dc"], ["/a"], None, persistent=False)
        self.assertIn("Persistent=false", tmr)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["timer", *args])
        return code, out.getvalue()

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = self.run_cli("/tmp/x.md", "--exec", "/bin/dc", "--unit-dir", d, "--at", "07:30")
            self.assertEqual(code, 0)
            self.assertIn("OnCalendar=*-*-* 07:30", out)
            self.assertEqual(os.listdir(d), [])

    def test_install_and_remove_files_only(self):
        with tempfile.TemporaryDirectory() as d:
            self.run_cli("/tmp/x.md", "--exec", "/bin/dc", "--unit-dir", d, "--name", "a",
                         "--calendar", "hourly", "--install", "--no-enable")
            self.assertEqual(sorted(os.listdir(d)), ["a.service", "a.timer"])
            self.assertIn("OnCalendar=hourly", Path(d, "a.timer").read_text())
            self.run_cli("--unit-dir", d, "--name", "a", "--remove", "--no-enable")
            self.assertEqual(os.listdir(d), [])

    def test_bad_time_rejected(self):
        with self.assertRaises(SystemExit):
            self.run_cli("/tmp/x.md", "--exec", "/bin/dc", "--at", "25:99")


if __name__ == "__main__":
    unittest.main()
