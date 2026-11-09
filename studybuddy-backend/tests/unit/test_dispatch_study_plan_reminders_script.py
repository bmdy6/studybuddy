import importlib.util
import json
import sys
from pathlib import Path

from app.core.infra.schemas.notification import DispatchStudyPlanReminderResponse


def _load_script_module():
    path = Path(__file__).parents[2] / "scripts" / "dispatch_study_plan_reminders.py"
    spec = importlib.util.spec_from_file_location("dispatch_study_plan_reminders", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _DummySession:
    closed = False

    def close(self):
        self.closed = True


def test_dispatch_script_outputs_summary(monkeypatch, capsys):
    module = _load_script_module()
    session = _DummySession()

    def _fake_dispatch_all(db, limit):
        assert db is session
        assert limit == 200
        return DispatchStudyPlanReminderResponse(created_count=0, skipped_count=3, notifications=[])

    monkeypatch.setattr(module, "SessionLocal", lambda: session)
    monkeypatch.setattr(module.reminder_service, "dispatch_all_study_plan_reminder_notifications", _fake_dispatch_all)
    monkeypatch.setattr(sys, "argv", ["dispatch_study_plan_reminders.py"])

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload == {"created_count": 0, "skipped_count": 3, "notification_ids": []}
    assert session.closed is True
