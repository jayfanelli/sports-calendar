from http.server import BaseHTTPRequestHandler
import urllib.request, urllib.parse, urllib.error, os, json
from datetime import datetime, timedelta

AF_BASE = "https://v3.football.api-sports.io"
AF_KEY  = os.environ.get("APIFOOTBALL_KEY", "")

# Maps API-Football league IDs to the competition codes used by the frontend
LEAGUE_CODE_MAP = {
    39:  'PL',    # Premier League
    40:  'ELC',   # Championship
    41:  'FL1',   # League One
    42:  'FL2',   # League Two
    45:  'FAC',   # FA Cup
    48:  'EFL',   # Carabao Cup
    2:   'CL',    # Champions League
    3:   'UEL',   # Europa League
    848: 'UECL',  # Conference League
}

def current_season():
    now = datetime.utcnow()
    return now.year if now.month >= 8 else now.year - 1

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params  = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        team_id = params.get("id", [None])[0]
        if not team_id:
            self.send_error(400, "Missing id"); return

        today  = datetime.utcnow()
        d_from = today.strftime('%Y-%m-%d')
        d_to   = (today + timedelta(days=180)).strftime('%Y-%m-%d')

        url = (
            f"{AF_BASE}/fixtures"
            f"?team={team_id}"
            f"&season={current_season()}"
            f"&from={d_from}"
            f"&to={d_to}"
            f"&status=NS"
        )
        req = urllib.request.Request(url, headers={"x-apisports-key": AF_KEY})

        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())

            # Transform to the same shape the frontend already knows how to parse
            matches = []
            for f in data.get('response', []):
                league_id = f['league']['id']
                matches.append({
                    'id':      f['fixture']['id'],
                    'utcDate': f['fixture']['date'],
                    'competition': {
                        'code': LEAGUE_CODE_MAP.get(league_id, str(league_id)),
                        'name': f['league']['name'],
                    },
                    'homeTeam': {
                        'id':   f['teams']['home']['id'],
                        'name': f['teams']['home']['name'],
                    },
                    'awayTeam': {
                        'id':   f['teams']['away']['id'],
                        'name': f['teams']['away']['name'],
                    },
                })

            body = json.dumps({'matches': matches}).encode()
            self.send_response(200)
            self.send_header("Content-Type",  "application/json")
            self.send_header("Cache-Control", "s-maxage=7200, stale-while-revalidate=3600")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
