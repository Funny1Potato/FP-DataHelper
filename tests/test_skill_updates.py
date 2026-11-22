import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import skill_updates


class SkillUpdateTests(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name).resolve()
        (self.root / "Version").write_text("2026.11.20 v0.3.9\n", encoding="utf-8")

    def test_published_package_is_required_before_notifying(self):
        release = {"tag_name": "0.3.10", "assets": [
            {"name": "FP-DataHelper.-.0.3.10.zip", "state": "starter"},
        ]}
        with patch.object(skill_updates, "urlopen", return_value=io.BytesIO(json.dumps(release).encode())):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                skill_updates.fetch_release_tag()
        release["assets"][0]["state"] = "uploaded"
        with patch.object(skill_updates, "urlopen", return_value=io.BytesIO(json.dumps(release).encode())):
            self.assertEqual(skill_updates.fetch_release_tag(), "0.3.10")

    def test_update_is_cached_and_force_checks_again(self):
        with patch.object(skill_updates, "fetch_release_tag", side_effect=["0.3.10", "0.3.8"]) as fetch:
            first = skill_updates.check_update(self.root)
            self.assertEqual(first["status"], "update_available")
            self.assertTrue(first["release_url"].endswith("/tag/0.3.10"))
            self.assertEqual(skill_updates.check_update(self.root), first)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(skill_updates.check_update(self.root, force=True)["status"], "current")
            self.assertEqual(fetch.call_count, 2)

    def test_failed_request_retries_after_one_hour(self):
        with (patch.object(skill_updates, "fetch_release_tag", side_effect=[OSError("offline"), "0.3.9"]) as fetch,
              patch.object(skill_updates.time, "time", return_value=1000) as clock):
            self.assertEqual(skill_updates.check_update(self.root)["status"], "unavailable")
            clock.return_value += skill_updates.RETRY_INTERVAL - 1
            self.assertEqual(skill_updates.check_update(self.root)["status"], "unavailable")
            self.assertEqual(fetch.call_count, 1)
            clock.return_value += 1
            self.assertEqual(skill_updates.check_update(self.root)["status"], "current")
            self.assertEqual(fetch.call_count, 2)

    def test_opt_out_still_allows_local_skill_comparison_and_manual_check(self):
        config = self.root / "config"
        config.mkdir()
        (config / "settings.json").write_text('{"auto_check_update": false}', encoding="utf-8")
        bundled = self.root / "skills" / "fp-datahelper"
        bundled.mkdir(parents=True)
        (bundled / "SKILL.md").write_text("new", encoding="utf-8")
        installed = self.root / "installed"
        installed.mkdir()
        (installed / "SKILL.md").write_text("old", encoding="utf-8")
        with patch.object(skill_updates, "fetch_release_tag", return_value="0.3.9") as fetch:
            result = skill_updates.check_update(self.root, installed)
            self.assertEqual(result["status"], "disabled")
            self.assertTrue(result["skill_refresh_available"])
            fetch.assert_not_called()
            self.assertEqual(skill_updates.check_update(self.root, force=True)["status"], "current")
            fetch.assert_called_once_with()
