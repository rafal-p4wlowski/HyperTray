"""Estimate the remaining headset battery time from the observed discharge rate.

Only time while the headset is switched on counts. The rate is fitted to the
moments the level dropped to a new low ("crossings"), which avoids the bias of
not knowing where within a percent the session started. A rate learned from
earlier sessions is kept on disk and used until the current session has
enough data.
"""
import json
import logging
import os
import time

log = logging.getLogger(__name__)

MIN_SESSION_S = 30 * 60    # need at least this much active time between crossings...
MIN_DROP = 2               # ...and at least this many percent dropped
MAX_STEP_S = 120           # longer gaps between updates (PC asleep) count as this much
RECHARGE_JUMP = 3          # a rise by this many percent means the battery was charged
LEARN_WEIGHT = 0.3         # weight of a finished session in the learned rate
CHARGING_STATES = ("Charging", "Fully charged")


class BatteryEstimator:
    def __init__(self, path=None):
        self.path = path
        self.learned_rate = self._load()   # percent per hour of active use
        self._active_s = 0.0
        self._last_tick = None
        self._crossings = []               # (active seconds, battery %) at each new low
        self._session_low = None

    # --- persistence ---
    def _load(self):
        if not self.path:
            return None
        try:
            with open(self.path, encoding="utf-8") as f:
                rate = float(json.load(f)["rate_pct_per_hour"])
            return rate if rate > 0 else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save(self):
        if not self.path or self.learned_rate is None:
            return
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"rate_pct_per_hour": round(self.learned_rate, 4)}, f)
        except OSError as e:
            log.warning("Cannot save battery statistics: %s", e)

    # --- sampling ---
    def update(self, battery, charging, connected, now=None):
        """Feed the current state. Call on every state change and periodically."""
        now = time.monotonic() if now is None else now
        if not connected or battery is None:
            self._last_tick = None          # headset off: the clock stops
            return
        if charging in CHARGING_STATES:
            self.finish_session()
            return

        if self._last_tick is not None:
            self._active_s += min(now - self._last_tick, MAX_STEP_S)
        self._last_tick = now

        if self._session_low is None:
            self._session_low = battery     # session start; not a crossing
        elif battery >= self._session_low + RECHARGE_JUMP:
            self.finish_session()           # charged while we weren't looking
            self._session_low = battery
            self._last_tick = now
        elif battery < self._session_low:
            self._session_low = battery
            self._crossings.append((self._active_s, battery))

    def session_rate(self):
        """Percent per hour fitted to this session, or None if too little data."""
        pts = self._crossings
        if len(pts) < 2:
            return None
        span = pts[-1][0] - pts[0][0]
        if span < MIN_SESSION_S or pts[0][1] - pts[-1][1] < MIN_DROP:
            return None
        # least-squares slope of battery over time
        n = len(pts)
        mean_t = sum(t for t, _ in pts) / n
        mean_b = sum(b for _, b in pts) / n
        var = sum((t - mean_t) ** 2 for t, _ in pts)
        slope = sum((t - mean_t) * (b - mean_b) for t, b in pts) / var  # % per second
        rate = -slope * 3600
        return rate if rate > 0 else None

    def finish_session(self):
        """Fold the current session into the learned rate and start over."""
        rate = self.session_rate()
        if rate is not None:
            if self.learned_rate is None:
                self.learned_rate = rate
            else:
                self.learned_rate += LEARN_WEIGHT * (rate - self.learned_rate)
            log.info("Battery discharge rate: session %.2f %%/h, learned %.2f %%/h",
                     rate, self.learned_rate)
            self._save()
        self._active_s = 0.0
        self._last_tick = None
        self._crossings = []
        self._session_low = None

    def hours_left(self, battery, charging):
        if battery is None or charging in CHARGING_STATES:
            return None
        rate = self.session_rate() or self.learned_rate
        if not rate:
            return None
        return battery / rate


def format_duration(hours):
    if hours is None:
        return None
    minutes = int(round(hours * 60))
    if minutes < 60:
        return f"~{max(minutes, 1)} min"
    if hours < 10:
        h, m = divmod(minutes, 60)
        return f"~{h} h {m:02d} min" if m else f"~{h} h"
    return f"~{int(round(hours))} h"
