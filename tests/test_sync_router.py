from __future__ import annotations

from unittest.mock import patch


class TestRunSync:
    def test_success_returns_stdout_stderr(self):
        from services.api.routers.sync import run_sync

        mock_result = {"success": True, "stdout": "synced 5 items", "stderr": ""}
        with patch("scripts.shared.sync_utils.run_sync_script", return_value=mock_result):
            result = run_sync()

        assert result["success"] is True
        assert result["stdout"] == "synced 5 items"
        assert result["stderr"] == ""

    def test_failure_returns_success_false(self):
        from services.api.routers.sync import run_sync

        mock_result = {"success": False, "stdout": "", "stderr": "error occurred"}
        with patch("scripts.shared.sync_utils.run_sync_script", return_value=mock_result):
            result = run_sync()

        assert result["success"] is False
        assert result["stderr"] == "error occurred"


class TestRunUnsync:
    def test_returns_removed_list(self):
        from services.api.routers.sync import run_unsync

        with patch("scripts.shared.agents.unsync_all", return_value=["/home/.claude/rules"]):
            result = run_unsync()

        assert result["success"] is True
        assert result["removed"] == ["/home/.claude/rules"]

    def test_empty_removal(self):
        from services.api.routers.sync import run_unsync

        with patch("scripts.shared.agents.unsync_all", return_value=[]):
            result = run_unsync()

        assert result["success"] is True
        assert result["removed"] == []
