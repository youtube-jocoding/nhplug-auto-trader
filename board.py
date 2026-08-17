"""지금 무엇을 들고 있고 예약이 무엇을 했는지 한 화면에서 봅니다. `python board.py`

예약이 보내는 글만으로는 한눈에 안 들어옵니다. 같은 내용을 표와 색으로 봅니다.

**읽기만 합니다.** 여기서는 주문도, 설정 변경도, 키 입력도 하지 않습니다.
그래서 계속 켜 두어도 됩니다. 설정은 setup.py, 주문은 trade.py 몫입니다.

표준 라이브러리만 씁니다(서버 프레임워크 없음).
"""

import html
import http.server
import json
import secrets
import sys
import time
import urllib.parse
import webbrowser

import setup  # 화면을 어떻게 띄울지(브라우저·에이전트·공개)는 이미 정해 두었습니다
import trade

REFRESH = 60  # 이 초마다 화면이 스스로 다시 그립니다. NH에 다시 묻지는 않습니다.
STALE = 600  # 남겨 둔 자료가 이만큼 오래됐으면, 화면을 열 때 알아서 다시 불러옵니다.
AFTER_ORDER = 45  # 주문을 낸 직후에는 이만큼만 기다립니다. 체결이 곧 잡힙니다.

HEAD = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>자동매매 현황</title>{refresh}
<style>{style}</style></head><body>"""

STYLE = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;padding:28px 20px 60px;background:#f4f6f5;color:#17211b;
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
main{max-width:720px;margin:0 auto}
h1{font-size:1.35rem;margin:0 0 4px;letter-spacing:-.02em}
.when{color:#66706a;font-size:.82rem;margin:0 0 18px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 18px}
.chips span{font-size:.78rem;padding:4px 10px;border-radius:999px;background:#e7ebe9;color:#3c4642}
.chips span.on{background:#e1f1e8;color:#075a33}
.chips span.live{background:#fdf7e8;color:#8a5f06;font-weight:600}
.card{background:#fff;border-radius:12px;padding:18px;margin:0 0 14px;
box-shadow:0 1px 2px rgba(20,40,30,.06)}
h2{font-size:.95rem;margin:0 0 12px;letter-spacing:-.01em}
.big{display:flex;gap:10px;margin:0 0 14px;flex-wrap:wrap}
.big div{flex:1;min-width:150px;background:#fff;border-radius:12px;padding:14px 16px;
box-shadow:0 1px 2px rgba(20,40,30,.06)}
.big b{display:block;font-size:1.3rem;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.big small{color:#66706a;font-size:.76rem}
table{width:100%;border-collapse:collapse;font-size:.87rem}
th,td{padding:9px 6px;border-bottom:1px solid #f0f3f1;text-align:left;white-space:nowrap}
th{font-weight:500;color:#8b948f;font-size:.75rem}
tr:last-child td{border-bottom:0}
td.num{text-align:right;font-variant-numeric:tabular-nums}
td.name{white-space:normal}
.up{color:#c22e2e;font-weight:600}
.down{color:#1552c7;font-weight:600}
.round{border-left:3px solid #e7ebe9;padding:0 0 0 12px;margin:0 0 14px}
.round:last-child{margin-bottom:0}
.round .t{font-size:.76rem;color:#8b948f}
.round p{margin:2px 0 6px;font-size:.9rem}
.did{font-size:.83rem;color:#3c4642;margin:0 0 3px}
.did b{font-weight:600}
.did.buy b{color:#c22e2e}
.did.sell b{color:#1552c7}
.tag{margin-left:8px;padding:1px 7px;border-radius:999px;background:#eef1ef;color:#66706a;
font-size:.7rem}
.tag.live{background:#fdf7e8;color:#8a5f06;font-weight:600}
.news{font-size:.78rem;color:#66706a;margin:0 0 3px}
.news.none{color:#c22e2e}
details{margin-top:4px}
summary{cursor:pointer;font-size:.78rem;color:#8b948f}
details p{font-size:.82rem;color:#66706a;margin:6px 0 0;white-space:pre-wrap}
.none{color:#8b948f;font-size:.87rem;margin:0}
a{color:#08733f}
a.btn{display:inline-block;text-decoration:none;background:#08733f;color:#fff;
padding:9px 16px;border-radius:8px;font-size:.88rem;font-weight:500}
footer{color:#8b948f;font-size:.76rem;text-align:center;margin-top:26px;line-height:1.7}
"""

WHEN = {"pre": "프리마켓", "regular": "정규장", "after": "애프터마켓", "closed": "닫힘"}


def esc(value):
    """NH가 준 종목 이름이 그대로 화면에 들어갑니다. 태그로 읽히지 않게 막습니다."""
    return html.escape(str(value))


def money_class(text):
    """손익 색. 오르면 빨강, 내리면 파랑(국내 증권사 화면과 같은 방향)."""
    text = str(text)
    if text.startswith("-"):
        return "down"
    return "up" if text.startswith("+") and float(text.rstrip("%")) != 0 else ""


def holdings_table(now):
    rows = now.get("보유") or []
    if not rows:
        return '<p class="none">아직 들고 있는 종목이 없습니다.</p>'
    head = "<tr><th>종목</th><th>수량</th><th>평균매입가</th><th>현재가</th><th>평가금액</th><th>손익</th></tr>"
    body = ""
    for row in rows:
        body += (
            f'<tr><td class="name">{esc(row.get("종목"))}</td>'
            f'<td class="num">{esc(row.get("수량"))}주</td>'
            f'<td class="num">{esc(row.get("평균매입가"))}</td>'
            f'<td class="num">{esc(row.get("현재가"))}</td>'
            f'<td class="num">{esc(row.get("평가금액", "-"))}</td>'
            f'<td class="num {money_class(row.get("손익", ""))}">{esc(row.get("손익"))}</td></tr>'
        )
    return f"<table>{head}{body}</table>"


def limits_table(caps):
    """얼마까지 걸리는지. 실제 돈으로 넘어가기 전에 여기부터 보게 합니다."""
    if not caps:
        return '<p class="none">아직 모릅니다. 예약이 한 번 돌면 여기에 나옵니다.</p>'
    rows = "".join(
        f'<tr><td>{esc(name)}</td><td class="num">{esc(value)}</td></tr>'
        for name, value in caps.items()
    )
    return f"<table>{rows}</table>"


def rounds_list(rounds):
    """예약이 돈 회차들. 무엇을 했는지가 먼저, 왜 했는지는 접어 둡니다."""
    if not rounds:
        return '<p class="none">아직 사고판 기록이 없습니다. 장이 열리면 여기에 쌓입니다.</p>'
    out = ""
    for one in rounds:
        # 어느 계좌에서 한 일인지 회차마다 붙입니다. 실거래는 눈에 띄게.
        where = one.get("계좌")
        tag = ""
        if where:
            tag = f'<span class="tag{" live" if where == "실제 계좌" else ""}">{esc(where)}</span>'
        out += f'<div class="round"><div class="t">{esc(one.get("시각"))}{tag}</div>'
        out += f'<p>{esc(one.get("요약"))}</p>'
        for item in one.get("처리함") or []:
            kind = {"매수": "buy", "매도": "sell"}.get(item.get("구분"), "")
            out += (
                f'<div class="did {kind}"><b>{esc(item.get("종목"))}</b> '
                f'{esc(item.get("한 일"))}</div>'
            )
            # 무엇을 보고 그렇게 했는지. 뉴스를 안 봤으면 그 사실이 그대로 보입니다.
            seen = item.get("뉴스")
            if seen:
                mark = " none" if seen == "확인하지 않음" else ""
                out += f'<div class="news{mark}">뉴스 · {esc(seen)}</div>'
            if item.get("이유"):
                out += (
                    f'<details><summary>왜 그렇게 했나</summary>'
                    f'<p>{esc(item["이유"])}</p></details>'
                )
        out += "</div>"
    return out


def page(saved):
    """남겨 둔 것을 화면 하나로. 파일이 없으면 무엇을 하면 되는지 알려 줍니다."""
    if not saved:
        # 여기서 막히면 대개 "예약이 도는 컴퓨터"와 "이 화면을 띄운 컴퓨터"가
        # 다른 경우입니다. 어느 폴더를 읽고 있는지 밝혀 두면 바로 알아챕니다.
        return HEAD.format(style=STYLE, refresh="") + (
            "<main><h1>자동매매 현황</h1>"
            '<div class="card"><p class="none">'
            "<b>아직 보여 드릴 것이 없습니다.</b><br><br>"
            "이 폴더에 예약이 돈 기록이 없고, 계좌를 불러오지도 못했습니다.<br>"
            "NH 키가 아직 없거나 연결이 안 되는 것일 수 있습니다. "
            "설정 화면에서 <b>저장하고 연결 확인</b>을 먼저 해 주세요.<br>"
            "예약은 도는데 계속 이 화면이라면, 예약이 도는 컴퓨터와 이 화면을 띄운 "
            "컴퓨터가 서로 다른 것입니다.</p>"
            '<p style="margin-top:14px"><a class="btn" href="/?load=1">다시 불러오기</a></p>'
            '<p class="none" style="margin-top:10px">NH에 계좌만 물어봅니다. 주문하지 않습니다.</p>'
            f'<p class="none" style="margin-top:14px">읽는 곳 {esc(trade.BOARD)}</p>'
            "</div></main></body></html>"
        )

    now = saved.get("지금") or {}
    live = saved.get("계좌") == "실제 계좌"
    chips = f'<span class="{"live" if live else "on"}">{esc(saved.get("계좌", "계좌 모름"))}</span>'
    chips += f'<span class="{"on" if saved.get("국내장") == "열림" else ""}">국내장 {esc(saved.get("국내장", "?"))}</span>'
    us = saved.get("미국장", "closed")
    chips += f'<span class="{"on" if us != "closed" else ""}">미국장 {esc(WHEN.get(us, us))}</span>'

    return HEAD.format(style=STYLE, refresh=f'<meta http-equiv="refresh" content="{REFRESH}">') + f"""
<main>
<h1>자동매매 현황</h1>
<p class="when">마지막 실행 {esc(saved.get("마지막실행", "-"))} · {REFRESH}초마다 저절로 새로 그리고
{STALE // 60}분 넘으면 계좌를 다시 불러옵니다 · <a href="/?load=1">지금 다시 불러오기</a></p>
<div class="chips">{chips}</div>

<div class="big">
  <div><small>들고 있는 종목</small><b>{esc(now.get("종목수", "-"))}</b></div>
  <div><small>주문 가능 현금</small><b>{esc(now.get("주문가능현금", "-"))}</b></div>
</div>

<div class="card">
  <h2>지금 들고 있는 것</h2>
  {holdings_table(now)}
</div>

<div class="card">
  <h2>지금 걸려 있는 한도</h2>
  {limits_table(saved.get("한도") or {})}
</div>

<div class="card">
  <h2>예약이 한 일</h2>
  {rounds_list(saved.get("회차") or [])}
</div>

<footer>이 화면은 보기만 합니다. 여기서는 주문도 설정 변경도 하지 않습니다.<br>
멈추고 싶으면 예약을 일시 중지하세요.</footer>
</main></body></html>"""


def read_board():
    try:
        return json.loads(trade.BOARD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_now():
    """NH에 계좌만 물어봐서 화면을 채웁니다. 주문하지 않습니다.

    조회 전용 모드만 부르므로, 이 화면에서 주문이 나갈 길은 여전히 없습니다.
    """
    try:
        setup.run_child(["trade.py", "--account"], timeout=120)
    except Exception as exc:
        print(f"계좌를 불러오지 못했습니다: {exc}")


def wait_before_asking(saved):
    """다시 물어보기까지 기다릴 시간.

    주문을 낸 직후에는 짧게 봅니다. 체결이 몇 초 뒤에 잡히는 일이 있어서,
    판 종목이 목록에 그대로 남아 있는 것처럼 보입니다.
    """
    return AFTER_ORDER if saved.get("확인필요") else STALE


def load_if_stale(server, saved):
    """보여 줄 것이 없거나 오래됐으면 알아서 불러옵니다.

    사람이 눌러야 채워지는 화면은 화면이 아니라 숙제입니다. 다만 새로고침마다
    NH에 묻지는 않도록, 실패했더라도 얼마간은 쉬었다 다시 시도합니다.
    """
    gap = wait_before_asking(saved)
    try:
        fresh = time.time() - trade.BOARD.stat().st_mtime < gap
    except OSError:
        fresh = False  # 파일이 아예 없으면 당연히 불러와야 합니다
    now = time.time()
    if fresh or now - getattr(server, "last_try", 0) < gap:
        return False
    server.last_try = now  # 먼저 적어 둡니다. 새로고침이 겹쳐도 두 번 나가지 않게.
    load_now()
    return True


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body, kind="text/html", location=None):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{kind}; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        if location:
            self.send_header("Location", location)
        token = getattr(self.server, "token", None)
        if token:
            self.send_header("Set-Cookie", f"nh_setup={token}; Path=/; SameSite=Strict")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not setup.Handler.allowed(self):
            return self._send(403, "주소 끝의 열쇠말이 없거나 틀렸습니다.", "text/plain")
        self.server.opened = True
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if query.get("load") == ["1"]:
            self.server.last_try = time.time()
            load_now()
            # 주소에 load가 남아 있으면 60초마다 NH에 다시 묻게 됩니다. 되돌려 보냅니다.
            return self._send(303, "불러왔습니다.", location="/")
        saved = read_board()
        if load_if_stale(self.server, saved):
            saved = read_board()  # 방금 받아 온 것으로 그립니다
        self._send(200, page(saved))


USAGE = """python board.py            지금 상황을 화면으로 봅니다
python board.py --public   서버에서, 포트를 이어 줄 방법이 없을 때만
    --port 8778            쓸 포트 (설정 화면과 겹치지 않게 8778을 씁니다)"""


def parse_args(argv):
    opts = {"public": False, "port": 8778}
    rest = iter(argv)
    for arg in rest:
        if arg == "--public":
            opts["public"] = True
        elif arg == "--port":
            try:
                opts["port"] = int(next(rest, ""))
            except ValueError:
                raise SystemExit("--port 뒤에는 숫자를 적어 주세요.")
        elif arg in ("-h", "--help"):
            raise SystemExit(USAGE)
        else:
            raise SystemExit(f"모르는 옵션입니다: {arg}\n\n{USAGE}")
    return opts


def main():
    opts = parse_args(sys.argv[1:])
    host = "0.0.0.0" if opts["public"] else "127.0.0.1"
    port = setup.free_port(host, opts["port"])
    # 스레드를 씁니다. 브라우저는 미리 연결만 열어 두고 아무것도 보내지 않는 일이
    # 있는데, 한 줄로 도는 서버는 그 빈 연결을 기다리다 화면 전체가 멈춥니다.
    server = http.server.ThreadingHTTPServer((host, port), Handler)
    server.opened = False
    rule = None

    if opts["public"]:
        server.token = secrets.token_urlsafe(9)
        only_from, _ = setup.ssh_peer()
        rule = setup.firewall_open(port, only_from)
        url = f"http://{setup.my_address()}:{port}/?t={server.token}"
        # 설정 화면과 달리 스스로 닫지 않습니다. 보기만 하는 화면이라 켜 둬도 됩니다.
        print(setup.public_guide(url, port, None, rule, only_from, what="현황 화면"))
    elif setup.has_browser():
        url = f"http://127.0.0.1:{port}"
        setup.after(0.5, lambda: webbrowser.open(url))
        print(f"현황 화면을 열었습니다: {url}")
    else:
        print(setup.agent_guide(port))
        setup.after(setup.WAIT_BEFORE_MANUAL,
                    lambda: print(setup.manual_guide(port)) if not server.opened else None)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        setup.firewall_close(rule)
        print("\n현황 화면을 닫았습니다.")


if __name__ == "__main__":
    main()
