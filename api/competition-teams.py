from http.server import BaseHTTPRequestHandler
import urllib.request, urllib.parse, urllib.error, os

FD_BASE = "https://api.football-data.org/v4"
FD_KEY  = os.environ.get("FD_API_KEY", "")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        comp   = params.get("comp", [None])[0]
        if not comp:
            self.send_error(400, "Missing comp"); return

        url = f"{FD_BASE}/competitions/{comp}/teams"
        self._proxy(url)

    def _proxy(self, url):
        req = urllib.request.Request(url, headers={"X-Auth-Token": FD_KEY})
        try:
            with urllib.request.urlopen(req) as r:
                body = r.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "s-maxage=86400, stale-while-revalidate=3600")
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
