"""Prop-account guardian: enforces OUR limits well inside the firm's rules via
the gateway kill switch. Layers (env-tunable, % of the relevant base):
  SOFT  — daily equity loss >= SOFT_PCT of prev-day close: kill switch ON
          (blocks new orders; brackets on open positions stay venue-side).
  HARD  — daily loss >= HARD_PCT: kill + FLATTEN everything. Released at the
          firm's day rollover (ROLL_UTC_HOUR, The5ers = 00:00 UTC+3 = 21 UTC).
  STATIC— equity <= INITIAL*(1-STATIC_PCT/100): kill + flatten, NOT auto-released.
  NEWS  — +/- NEWS_PAD_MIN minutes around high-impact USD/EUR events
          (ForexFactory weekly feed): kill switch ON, no flatten.
  FRIDAY— from Fri FRI_FLAT_UTC:00 UTC: kill + flatten; released Sunday 22:10 UTC.
State survives restarts in /state/guardian.json."""
import json, os, time, urllib.request, datetime as dt

GW = os.environ.get("GATEWAY", "http://mt5-gateway:5001")
KEY = os.environ["API_KEY"]
INITIAL = float(os.environ.get("INITIAL", "20000"))
SOFT = float(os.environ.get("SOFT_PCT", "2.5"))
HARD = float(os.environ.get("HARD_PCT", "3.5"))
STATIC = float(os.environ.get("STATIC_PCT", "6"))
ROLL = int(os.environ.get("ROLL_UTC_HOUR", "21"))
PAD = int(os.environ.get("NEWS_PAD_MIN", "5"))
FRI = int(os.environ.get("FRI_FLAT_UTC", "20"))
FEED = os.environ.get("NEWS_FEED", "https://nfs.faireconomy.media/ff_calendar_thisweek.json")
STATE = "/state/guardian.json"
TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_CHAT = os.environ.get("TG_CHAT", "")

def notify(text):
    """Best-effort Telegram push; alerts must never break the guard loop."""
    if not (TG_TOKEN and TG_CHAT): return
    try:
        body = json.dumps({"chat_id": TG_CHAT, "text": "[guardian] " + text}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                                     data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as ex:
        log("telegram error:", ex)

def api(path, method="GET"):
    r = urllib.request.Request(GW + path, method=method, headers={"Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read())

def log(*a): print(dt.datetime.now(dt.timezone.utc).strftime("%m-%d %H:%M:%S"), *a, flush=True)

def load():
    try: return json.load(open(STATE))
    except Exception: return {}
def save(st): json.dump(st, open(STATE, "w"))

def day_anchor(now):
    """The firm's trading day: rolls at ROLL UTC."""
    d = now.date()
    if now.hour < ROLL: d -= dt.timedelta(days=1)
    return d.isoformat()

def fetch_news():
    try:
        with urllib.request.urlopen(urllib.request.Request(FEED, headers={"User-Agent": "Mozilla/5.0 (guardian)"}), timeout=30) as r: events = json.loads(r.read())
        out = []
        for e in events:
            if str(e.get("impact", "")).lower() != "high": continue
            if e.get("country") not in ("USD", "EUR"): continue
            try: ts = dt.datetime.fromisoformat(e["date"]).timestamp()
            except Exception: continue
            out.append(ts)
        return sorted(out)
    except Exception as ex:
        log("news feed error:", ex); return None

st = load()
news, news_at = None, 0
log(f"guardian up: initial={INITIAL} soft={SOFT}% hard={HARD}% static={STATIC}% roll={ROLL}UTC pad={PAD}m")
while True:
    try:
        now = dt.datetime.now(dt.timezone.utc)
        if time.time() - news_at > (3600 if news is None else 6 * 3600):
            news_at = time.time()
            n = fetch_news()
            if n is not None:
                news = n; log(f"news feed: {len(news)} high-impact USD/EUR events this week")
        acct = api("/account"); acct = acct.get("data", acct)
        eq = float(acct.get("equity") or 0)
        anchor = day_anchor(now)
        if st.get("day") != anchor:
            prev = st.get("equity_now", eq)
            st.update({"day": anchor, "prev_close": prev, "daily_lock": False})
            if st.get("lock") == "daily": st["lock"] = None
            log(f"day rollover -> prev_close={prev:.2f}")
        st["equity_now"] = eq
        prev_close = float(st.get("prev_close") or eq)
        dd_day = (prev_close - eq) / prev_close * 100 if prev_close > 0 else 0
        static_floor = INITIAL * (1 - STATIC / 100)
        in_news = news and any(abs(now.timestamp() - t) <= PAD * 60 for t in news)
        friday = (now.weekday() == 4 and now.hour >= FRI) or now.weekday() == 5 or (now.weekday() == 6 and (now.hour < 22 or (now.hour == 22 and now.minute < 10)))
        want_kill, want_flat, reason = False, False, None
        if eq <= static_floor:
            want_kill, want_flat, reason = True, True, "STATIC"
            st["lock"] = "static"
        elif st.get("lock") == "static":
            want_kill, reason = True, "STATIC-HOLD"
        elif dd_day >= HARD or st.get("daily_lock"):
            want_kill, reason = True, "DAILY-HARD"
            if not st.get("daily_lock"): want_flat = True
            st["daily_lock"] = True; st["lock"] = "daily"
        elif dd_day >= SOFT:
            want_kill, reason = True, "DAILY-SOFT"
        elif friday:
            want_kill, reason = True, "WEEKEND"
            if now.weekday() == 4 and not st.get("fri_flat") == anchor:
                want_flat = True; st["fri_flat"] = anchor
        elif in_news:
            want_kill, reason = True, "NEWS"
        ks = bool(api("/health").get("kill_switch_active"))
        if want_kill and not ks:
            api("/kill" + ("?flatten=true" if want_flat else ""), "POST")
            st["guard_kill"] = True
            log(f"KILL engaged ({reason}) eq={eq:.2f} dayDD={dd_day:.2f}% flatten={want_flat}")
            notify(f"KILL engaged ({reason}) equity={eq:.2f} dayDD={dd_day:.2f}% flatten={want_flat}")
        elif want_kill and want_flat:
            api("/kill?flatten=true", "POST"); st["guard_kill"] = True; log(f"flatten re-issued ({reason})")
        elif not want_kill and ks:
            # only release a switch the guardian itself engaged — a manual
            # operator kill stays engaged until the operator releases it
            if st.get("guard_kill"):
                api("/kill/release", "POST"); st["guard_kill"] = False
                log(f"kill released eq={eq:.2f} dayDD={dd_day:.2f}%")
                notify(f"kill released, equity={eq:.2f}")
        elif not want_kill and not ks:
            st["guard_kill"] = False
        save(st)
    except Exception as ex:
        log("loop error:", ex)
    time.sleep(30)
