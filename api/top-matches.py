from http.server import BaseHTTPRequestHandler
import urllib.request, urllib.error, os, json
from concurrent.futures import ThreadPoolExecutor, as_completed

FD_BASE = "https://api.football-data.org/v4"
FD_KEY  = os.environ.get("FD_API_KEY", "")

LEAGUES    = ['PL', 'ELC', 'PD', 'BL1', 'SA', 'FL1']
EURO_COMPS = ['CL', 'UEL', 'UECL']
TOP_N      = 6

def fd_get(path):
    req = urllib.request.Request(
        f"{FD_BASE}{path}",
        headers={"X-Auth-Token": FD_KEY}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def fetch_standings(code):
    try:
        data       = fd_get(f"/competitions/{code}/standings")
        standings  = data.get('standings', [])
        total      = next((s for s in standings if s['type'] == 'TOTAL'), standings[0] if standings else None)
        if not total:
            return code, {}
        comp_label = data['competition']['name']
        result = {}
        for row in total['table'][:TOP_N]:
            tid = row['team']['id']
            result[tid] = {
                'position':   row['position'],
                'leagueCode': code,
                'leagueLabel': comp_label,
            }
        return code, result
    except Exception:
        return code, {}

def fetch_matches(code):
    try:
        data       = fd_get(f"/competitions/{code}/matches?status=SCHEDULED")
        comp_label = data['competition']['name']
        return code, comp_label, data.get('matches', [])
    except Exception:
        return code, code, []

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # ── 1. Fetch standings for all domestic leagues concurrently ──────
            top_teams = {}  # team_id -> {position, leagueCode, leagueLabel}
            with ThreadPoolExecutor(max_workers=len(LEAGUES)) as ex:
                for _, teams in ex.map(fetch_standings, LEAGUES):
                    top_teams.update(teams)

            top_ids = set(top_teams.keys())

            # ── 2. Fetch scheduled matches for all comps concurrently ─────────
            all_comps   = LEAGUES + EURO_COMPS
            comp_results = []
            with ThreadPoolExecutor(max_workers=len(all_comps)) as ex:
                comp_results = list(ex.map(fetch_matches, all_comps))

            # Process domestic leagues first so euro-comp dupes get dropped
            comp_results.sort(key=lambda x: (0 if x[0] in LEAGUES else 1))

            # ── 3. Filter to top-6 vs top-6 ──────────────────────────────────
            results  = []
            seen_ids = set()

            for code, comp_label, matches in comp_results:
                for m in matches:
                    mid   = m['id']
                    ht_id = m['homeTeam']['id']
                    at_id = m['awayTeam']['id']

                    if mid in seen_ids:
                        continue
                    if ht_id not in top_ids or at_id not in top_ids:
                        continue

                    seen_ids.add(mid)
                    ht = top_teams.get(ht_id, {})
                    at = top_teams.get(at_id, {})

                    results.append({
                        'id':               mid,
                        'competition':      code,
                        'competitionLabel': comp_label,
                        'homeTeam': {
                            'id':        ht_id,
                            'name':      m['homeTeam']['name'],
                            'position':  ht.get('position'),
                            'leagueCode': ht.get('leagueCode'),
                        },
                        'awayTeam': {
                            'id':        at_id,
                            'name':      m['awayTeam']['name'],
                            'position':  at.get('position'),
                            'leagueCode': at.get('leagueCode'),
                        },
                        'utcDate': m['utcDate'],
                    })

            body = json.dumps({'matches': results}).encode()
            self.send_response(200)
            self.send_header("Content-Type",  "application/json")
            self.send_header("Cache-Control", "s-maxage=3600, stale-while-revalidate=1800")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        except Exception as e:
            body = json.dumps({'error': str(e), 'matches': []}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
