"""Atomic local quota refresh and billing; all amounts are integer units."""

from datetime import datetime, timedelta, timezone

from .storage import now


def refresh_subscriptions(db, user_id=None, *, at=None):
    instant = datetime.fromisoformat(at or now()).astimezone(timezone.utc)
    stamp = instant.isoformat(timespec="seconds")

    def refresh():
        rows = db.all("SELECT * FROM subscriptions WHERE status='active'" +
                      (" AND user_id=?" if user_id is not None else ""),
                      (user_id,) if user_id is not None else ())
        changed = 0
        for row in rows:
            expiry = datetime.fromisoformat(row['expires_at'])
            reset = datetime.fromisoformat(row['reset_at'])
            expiry = expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry
            reset = reset.replace(tzinfo=timezone.utc) if reset.tzinfo is None else reset
            if expiry <= instant:
                db.execute("UPDATE subscriptions SET status='expired' WHERE id=?", (row['id'],))
                db.event(None, 'subscription_expired', f"客户 #{row['user_id']} 的套餐 #{row['id']} 已到期")
                changed += 1
            elif reset <= instant:
                period = timedelta(days=row['period_days'])
                cycles = (instant - reset) // period + 1
                next_reset = (reset + cycles * period).astimezone(timezone.utc).isoformat(timespec='seconds')
                db.execute("UPDATE subscriptions SET used_units=0,reset_at=? WHERE id=?", (next_reset, row['id']))
                db.execute("INSERT INTO quota_ledger(user_id,subscription_id,kind,delta_units,used_after_units,period_end,created_at) VALUES (?,?,'refresh',?,0,?,?)",
                           (row['user_id'], row['id'], -row['used_units'], next_reset, stamp))
                db.event(None, 'quota_refreshed', f"客户 #{row['user_id']} 的套餐 #{row['id']} 已刷新；跨过 {cycles} 个周期")
                changed += 1
        return changed

    with db.lock:
        if db.connection.in_transaction:
            return refresh()
        with db.transaction():
            return refresh()
