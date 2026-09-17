from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import crypto_advisor.alerts as alerts_mod
from crypto_advisor.alerts import CooldownStore


def test_should_fire_true_when_never_sent():
    store = CooldownStore({})
    now = datetime.now(timezone.utc)
    assert store.should_fire("bitcoin", "big_move", 120, now) is True


def test_should_fire_false_within_cooldown_window():
    store = CooldownStore({})
    now = datetime.now(timezone.utc)
    store.record("bitcoin", "big_move", now)
    still_within = now + timedelta(minutes=60)
    assert store.should_fire("bitcoin", "big_move", 120, still_within) is False


def test_should_fire_true_after_cooldown_elapses():
    store = CooldownStore({})
    now = datetime.now(timezone.utc)
    store.record("bitcoin", "big_move", now)
    after_cooldown = now + timedelta(minutes=121)
    assert store.should_fire("bitcoin", "big_move", 120, after_cooldown) is True


def test_cooldown_is_per_coin_and_alert_type():
    store = CooldownStore({})
    now = datetime.now(timezone.utc)
    store.record("bitcoin", "big_move", now)
    # different coin, same alert type -> unaffected
    assert store.should_fire("ethereum", "big_move", 120, now) is True
    # same coin, different alert type -> unaffected
    assert store.should_fire("bitcoin", "stop_hit", 120, now) is True


def test_store_load_save_roundtrip(tmp_path, monkeypatch):
    fake_path = tmp_path / "alert_cooldowns.json"
    monkeypatch.setattr(alerts_mod, "COOLDOWN_PATH", fake_path)
    monkeypatch.setattr(alerts_mod, "DATA_DIR", tmp_path)
    store = CooldownStore({})
    now = datetime.now(timezone.utc)
    store.record("bitcoin", "action_change", now)
    store.save()

    assert fake_path.exists()
    reloaded = CooldownStore.load()
    assert reloaded.should_fire("bitcoin", "action_change", 120, now + timedelta(minutes=1)) is False


def test_load_handles_corrupt_file_gracefully(tmp_path, monkeypatch):
    fake_path = tmp_path / "alert_cooldowns.json"
    fake_path.write_text("{not valid json")
    monkeypatch.setattr(alerts_mod, "COOLDOWN_PATH", fake_path)
    store = CooldownStore.load()
    assert store.last_sent == {}
