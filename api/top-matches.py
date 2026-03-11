from http.server import BaseHTTPRequestHandler
import urllib.request, urllib.error, os, json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import partial

AF_BASE = "https://v3.football.api-sports.io"
AF_KEY  = os.environ.get("APIFOOTBALL_KEY", "")

LEAGUES = [
    {'id': 39,  'code': 'PL',   'label': 'Premier League'},
    {'id': 40,  'code': 'ELC',  'label': 'Championship'},
    {'id': 140, 'code': 'PD',   'label': 'La Liga'},
    {'id': 78,  'code': 'BL1',  'label': 'Bundesliga'},
    {'id': 135, 'code': 'SA',   'label': 'Serie A'},
    {'id': 61,  'code': 'FL1',  'label': 'Ligue 1'},
]
EURO_COMPS = [
    {'id': 2,   'code': 'CL',   'label': 'Champions League'},
    {'id': 3,   'code': 'UEL',  'label': 'Europa League'},
    {'id': 848, 'code': 'UECL', 'label': 'Conference League'},
]
TOP_N        = 6
LEAGUE_CODES = {l['code'] for l in LEAGUES}

def current_season():
    now = datetime.utcnow()
    # European seasons start in Aug: 2025/26 season → season ID 2025
    return now.year if now.month >= 8 else now.year - 1

def af_get(path):
    req = urllib.request.Request(
        f"{AF_BASE}{path}",
        headers={"x-apisports-key": AF_KEY}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def fetch_standings(league):
    try:
        data      = af_get(f"/standings?league={league['id']}&season={current_season()}")
        responses = data.get('response', [])
        if not responses:
            return league['code'], {}
        table  = responses[0]['league']['standings'][0]
        result = {}
        for row in table[:TOP_N]:
            tid = row['team']['id']
            result[tid] = {
                'position':    row['rank'],
                'leagueCode':  league['code'],
                'leagueLabel': league['label'],
            }
        return league['code'], result
    except Exception:
        return league['code'], {}

def fetch_fixtures(comp, date_from, date_to):
    try:
        path = (
            f"/fixtures"
            f"?league={comp['id']}"
            f"&season={current_season()}"
            f"&from={date_from}"
            f"&to={date_to}"
            f"&status=NS"
        )
        data = af_get(path)
        return comp['code'], comp['label'], data.get('response', [])
    except Exception:
        return comp['code'], comp['label'], []

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            today  = datetime.utcnow()
            d_from = today.strftime('%Y-%m-%d')
            d_to   = (today + timedelta(days=90)).strftime('%Y-%m-%d')

            # ── 1. Fetch standings for all domestic leagues ───────────────────
            # max_workers=3 keeps concurrent requests manageable
            top_teams = {}
            with ThreadPoolExecutor(max_workers=3) as ex:
                for _, teams in ex.map(fetch_standings, LEAGUES):
                    top_teams.update(teams)

            top_ids = set(top_teams.keys())

            # ── 2. Fetch scheduled fixtures for all comps ─────────────────────
            all_comps  = LEAGUES + EURO_COMPS
            fetch_fn   = partial(fetch_fixtures, date_from=d_from, date_to=d_to)
            with ThreadPoolExecutor(max_workers=3) as ex:
                comp_results = list(ex.map(fetch_fn, all_comps))

            # Domestic leagues first so euro-comp duplicates get dropped
            comp_results.sort(key=lambda x: (0 if x[0] in LEAGUE_CODES else 1))

            # ── 3. Filter to top-6 vs top-6 ──────────────────────────────────
            results  = []
            seen_ids = set()

            for code, comp_label, fixtures in comp_results:
                for f in fixtures:
                    fid   = f['fixture']['id']
                    ht_id = f['teams']['home']['id']
                    at_id = f['teams']['away']['id']

                    if fid in seen_ids:
                        continue
                    if ht_id not in top_ids or at_id not in top_ids:
                        continue

                    seen_ids.add(fid)
                    ht = top_teams.get(ht_id, {})
                    at = top_teams.get(at_id, {})

                    results.append({
                        'id':               fid,
                        'competition':      code,
                        'competitionLabel': comp_label,
                        'homeTeam': {
                            'id':         ht_id,
                            'name':       f['teams']['home']['name'],
                            'position':   ht.get('position'),
                            'leagueCode': ht.get('leagueCode'),
                        },
                        'awayTeam': {
                            'id':         at_id,
                            'name':       f['teams']['away']['name'],
                            'position':   at.get('position'),
                            'leagueCode': at.get('leagueCode'),
                        },
                        'utcDate': f['fixture']['date'],
                    })

            body = json.dumps({'matches': results}).encode()
            self.send_response(200)
            self.send_header("Content-Type",  "application/json")
            # Cache for 24 hours — one batch of API calls per day per edge node
            self.send_header("Cache-Control", "s-maxage=86400, stale-while-revalidate=3600")
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
