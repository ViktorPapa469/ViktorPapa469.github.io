"""The trade plan every setup is scored by, shared by the live scan (open positions, daily loss) and the track record."""


def walk(bars, side, entry, stop, t1, t2, time_exit_ok, unit=None):
    """Follow the plan over bars (after the fill), deciding by whichever level is reached first.
    A stop hit before the first target is a loss even if price later recovers to the target.
    entry is the price actually paid; unit is the size of 1R in rupees a share (default: entry to stop). With a late
    fill, pass the planned stop distance as unit: the position was sized from the plan, so a stop then costs more
    than 1R and the first target pays less than 1.5R.
    Returns (outcome, R, exit price, done, events) where events = {"stop"|"t1"|"t2"|"entry": bar time}."""
    s, risk = (1 if side == "long" else -1), (unit or abs(entry - stop))
    ev = {}
    if not risk:
        return "No risk", 0.0, entry, True, ev
    R = lambda px: s * (px - entry) / risk   # noqa: E731
    half = False
    for when, b in bars.iterrows():
        hi, lo = (b["high"], b["low"]) if s == 1 else (-b["low"], -b["high"])   # mirror shorts
        st, a, z = s * (entry if half else stop), s * t1, s * t2
        if lo <= st:                       # stop first when both sit in one bar
            if half:
                ev["entry"] = when
                return "First target, rest out at entry", 0.5 * R(t1), entry, True, ev
            ev["stop"] = when
            return "Stop", R(stop), stop, True, ev
        if not half and hi >= a:
            half = True
            ev["t1"] = when
            if hi >= z:
                ev["t2"] = when
                return "Both targets", 0.5 * R(t1) + 0.5 * R(t2), t2, True, ev
            continue
        if half and hi >= z:
            ev["t2"] = when
            return "Both targets", 0.5 * R(t1) + 0.5 * R(t2), t2, True, ev
    if not len(bars):
        return "Open", 0.0, entry, False, ev
    last = float(bars["close"].iloc[-1])
    r = 0.5 * R(t1) + 0.5 * R(last) if half else R(last)
    if time_exit_ok:
        return ("First target, rest at time exit" if half else "Time exit"), r, last, True, ev
    return ("Open, first target booked" if half else "Open"), r, last, False, ev
