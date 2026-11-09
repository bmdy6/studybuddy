import importlib.util
import json
from pathlib import Path


def _load_script_module():
    path = Path(__file__).parents[2] / "scripts" / "dispatch_wechat_parent_reminders.py"
    spec = importlib.util.spec_from_file_location("dispatch_wechat_parent_reminders", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _DummySession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_dispatch_wechat_script_outputs_safe_counts(monkeypatch, capsys):
    module = _load_script_module()
    session = _DummySession()
    monkeypatch.setattr(module, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        module.wechat_dispatch,
        "dispatch_parent_reminders",
        lambda db: {"sent": 1, "paused": 0, "failed": 0} if db is session else None,
    )
    monkeypatch.setattr(
        module.dispatch,
        "dispatch_due_growth_summaries",
        lambda db, send_ilink: (
            {"sent": 1, "paused": 2, "failed": 0} if db is session and send_ilink is module.messaging.send_ilink_text else None
        ),
    )

    module.main()

    out = json.loads(capsys.readouterr().out)
    assert out["sent"] == 2
    assert out["paused"] == 2
    assert out["failed"] == 0
    assert "ts" in out and out["ts"]
