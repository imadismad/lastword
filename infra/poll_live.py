"""Poll the dashboard mesh status repeatedly until nugget-2 (0d60) is heard on-air."""
import urllib.request, json, time, io

OUT = r"C:\Users\Dell_Arte_III\Desktop\hackathon_essec_secure_horizon\poll.txt"
log = io.open(OUT, "w", encoding="utf-8")
def w(s):
    log.write(s + "\n"); log.flush()

for i in range(8):  # up to ~8 polls
    try:
        d = urllib.request.urlopen("http://127.0.0.1:8090/api/mesh/status?refresh=1", timeout=70).read().decode()
        j = json.loads(d)
    except Exception as e:
        w(f"poll {i}: ERR {e}")
        time.sleep(5)
        continue
    if not j.get("reachable"):
        w(f"poll {i}: busy ({j.get('detail','')[:40]})")
        time.sleep(5)
        continue
    peers = j.get("peers", [])
    live = [p for p in peers if p.get("live")]
    n2 = next((p for p in peers if "0d60" in p.get("id","")), None)
    w(f"poll {i}: live={[p['id'] for p in live]} nugget2_live={bool(n2 and n2.get('live'))} "
      f"nugget2_live_now={bool(n2 and n2.get('live_now'))} nugget2_heard_s_ago={n2.get('heard_s_ago') if n2 else None}")
    if n2 and n2.get("live"):
        w("RESULT: NUGGET-2 IS LIVE ON THE DASHBOARD")
        break
    time.sleep(3)
else:
    w("RESULT: did not catch nugget-2 beacon in the poll window")
log.close()
