"""브라우저에서 설정을 끝냅니다. `python setup.py`

텍스트 편집기로 .env를 여는 일이 없도록, 키 붙여넣기 → 연결 확인까지 한 화면에서
합니다. 전략 상담은 Codex 본체에서 하도록 프롬프트를 복사해 줍니다.
표준 라이브러리만 씁니다(서버 프레임워크 없음).
"""

import http.server
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

from dotenv import dotenv_values

HERE = Path(__file__).parent
ENV = HERE / ".env"
SCHEDULE = HERE / "schedule.txt"


def schedule_text():
    """예약에 넣을 글. 파일 하나에만 둬서 화면과 README가 어긋나지 않게 합니다."""
    try:
        return SCHEDULE.read_text(encoding="utf-8").strip()
    except OSError:
        return "schedule.txt 를 찾지 못했습니다. 저장소에서 다시 받아 주세요."

# Codex 본체에 붙여넣을 프롬프트. 웹 폼으로 답을 받는 것보다, 사용자가 Codex와
# 직접 대화하면서 되묻고 다듬는 편이 훨씬 자연스럽습니다. 그래서 여기서는
# "상담해서 파일을 고쳐라"라고 시키기만 합니다.
CODEX_PROMPT = """이 폴더의 strategy.py 하나만 고쳐서 내 투자 성향에 맞는 자동매매 전략을 만들어줘.

━━ 먼저 상담부터 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

파일을 고치기 전에 나와 대화해서 성향을 파악해. 투자 상담사처럼 해줘.

- **질문은 한 번에 하나만.** 내 답을 듣고 나서 다음 질문을 해.
  질문을 목록으로 한꺼번에 늘어놓지 마. 그러면 상담이 아니라 설문지야.
- 내 답에 따라 다음 질문을 정해. 앞뒤가 안 맞으면 그 자리에서 되물어.
- 6~8번 주고받고 끝내. 그 이상 끌지 마.
- 쉬운 말로 물어. "MACD를 쓸까요?"가 아니라 "오르는 흐름을 따라갈까요,
  아니면 싸졌을 때 담을까요?" 처럼.

이 정도는 알아내야 해. 순서와 표현은 네가 정해:
  얼마를 굴릴지 · 한 종목에 넣을 금액 · 몇 종목까지 들고 갈지
  얼마나 떨어지면 못 견디는지 · 얼마나 오르면 만족하는지
  자주 사고팔고 싶은지 오래 들고 가고 싶은지
  관심 있는 회사나 업종이 있는지
    → 없다고 하면 성향에 맞는 종목을 네가 3~5개 골라 주고 **왜 그 종목인지 한 줄씩** 설명해
    → 있다고 하면 그 종목이 성향과 맞는지 봐 주고, 안 맞으면 솔직히 말해
  미국 주식도 할지

다 듣고 나면 **파일을 고치기 전에** 이렇게 정리해서 보여주고 "이대로 할까요?"라고 물어봐:
  종목 — 각각 왜 이 종목인지 한 줄
  한 종목에 넣을 금액 · 최대 보유 종목 수
  손절선 · 익절선
  어떤 신호에 사고 어떤 신호에 파는지 한 줄 요약

내가 좋다고 하면 그때 strategy.py를 고쳐. 다른 파일은 건드리지 마.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

사고팔지는 **장중에 Codex가 그때그때 판단해.** strategy.py는 판단을 지시하는
투자 원칙(INSTRUCTIONS)과, 그 판단을 받아 최종 결정하는 decide(m)를 담는 파일이야.
내 성향은 주로 INSTRUCTIONS 글에 담고, 넘지 말아야 할 선만 숫자로 박아 줘.

strategy.py가 지켜야 하는 약속:
- SYMBOLS: 국내 6자리 종목코드 문자열 리스트 (삼성전자 005930, SK하이닉스 000660,
  카카오 035720, NAVER 035420, 현대차 005380, LG에너지솔루션 373220)
- US_SYMBOLS: 미국 티커 대문자 리스트 (애플 AAPL, 마이크로소프트 MSFT, 엔비디아 NVDA,
  테슬라 TSLA, 구글 GOOGL). 미국을 안 하면 빈 리스트 []
- BUY_AMOUNT: 국내 한 종목에 넣을 원화 금액 (정수)
- US_BUY_AMOUNT: 미국 한 종목에 넣을 달러 금액 (정수)
- MAX_HOLDINGS: 동시에 들고 갈 최대 종목 수 (정수)
- decide(m) 함수: ("buy" 또는 "sell" 또는 "hold", 이유 문자열) 튜플을 돌려줄 것
- INSTRUCTIONS: 장중에 판단할 Codex에게 그대로 전달할 투자 원칙 (한국어 여러 줄)
- facts(m): Codex에게 더 보여 줄 사실을 문자열 리스트로 돌려주는 함수

장중 판단자에게 가는 것은 이것뿐이야:
  현재가 · 최근 20일 종가 · 5일/20일 평균 · 52주 최고/최저 · 거래대금 · 보유 상태
  facts(m)가 낸 지표 (지금은 5·20·60일 이동평균, RSI(14), MACD와 신호선)
  그리고 판단자가 직접 찾아본 뉴스 제목

**여기에 없는 값을 INSTRUCTIONS에서 부르면 안 돼.** 예를 들어 "볼린저 상단을 넘으면"
이라고 써 놓고 facts에서 안 넘기면, 판단자가 종가로 암산하다 틀린 값을 쓴다.
지표를 더 쓰기로 했으면 facts(m)에 계산해서 한 줄 더 붙여. 안 쓸 지표는 지워도 돼.

decide에 들어오는 m에서 읽을 수 있는 값:
  code, name, market("kr"/"us"), currency("KRW"/"USD"), price, closes(오래된 것부터인
  종가 리스트), held(bool), qty, avg, pnl_pct, cash
  ai: {"decision": "buy"|"sell"|"hold", "reason": "..."} — 장중 Codex의 판단.
      None이면 판단을 받지 못한 것이니 절대 사면 안 돼

decide()는 이 순서를 지켜:
1) 보유 중이고 손절·익절 선에 닿았으면 Codex 판단과 무관하게 sell
   (Codex가 죽은 날에도 손절은 돌아야 해)
2) 미보유인데 거를 조건(거래대금 부족 등)이면 hold
3) m["ai"]가 없거나 decision이 이상하면 hold
4) 나머지는 m["ai"]["decision"]을 따르고, 이유는 m["ai"]["reason"]을 그대로 써

규칙:
- 계산용 표준 라이브러리는 자유롭게 써도 돼(math, statistics, random, re, json,
  datetime, zoneinfo, itertools, functools, collections, decimal …).
  다만 바깥과 이야기하는 것은 금지: os, sys, io, pathlib, socket, urllib, requests,
  subprocess, importlib 같은 파일·네트워크·프로세스 모듈과 eval/exec/open
- closes가 비어 있거나 짧아도 터지지 않게 할 것
- 주석과 이유 문자열은 한국어로, 초보자가 읽어서 이해할 수 있게
- 금액을 이유에 쓸 때는 통화를 맞출 것 (원 / $)

다 고치고 나면 이 명령으로 검사해줘. 통과해야 끝난 거야:
  python check.py
"""

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>자동매매 설정</title><style>
*{box-sizing:border-box}
body{font-family:-apple-system,'Malgun Gothic',sans-serif;max-width:640px;margin:0 auto;
padding:32px 20px 80px;color:#17211b;line-height:1.6;background:#fff}
h1{font-size:1.5rem;margin:0 0 4px}
.sub{color:#66706a;margin:0 0 28px}
section{border:1px solid #d9dfdb;border-radius:12px;padding:20px;margin-bottom:16px}
h2{font-size:1.05rem;margin:0 0 4px;display:flex;align-items:center;gap:8px}
h2 b{width:22px;height:22px;border-radius:50%;background:#e1f1e8;color:#075a33;
font-size:.78rem;display:inline-flex;align-items:center;justify-content:center;flex:none}
h2 small{margin-left:auto;font-weight:400;font-size:.78rem;color:#66706a}
p.help{color:#66706a;font-size:.88rem;margin:4px 0 14px}
label{display:block;margin-bottom:12px}
label span{display:block;font-size:.85rem;margin-bottom:4px}
input{width:100%;padding:10px 12px;border:1px solid #d9dfdb;border-radius:8px;
font-size:.95rem;font-family:inherit}
button{background:#08733f;color:#fff;border:0;border-radius:8px;padding:12px 18px;
font-size:.95rem;font-weight:600;cursor:pointer;width:100%}
button:disabled{background:#b6bcb8;cursor:default}
button.ghost{background:#fff;color:#17211b;border:1px solid #d9dfdb}
.msg{margin-top:12px;padding:10px 12px;border-radius:8px;font-size:.88rem;white-space:pre-wrap;
font-family:ui-monospace,Menlo,Consolas,monospace}
.ok{background:#f0f7f3;color:#075a33}
.err{background:#fff3f2;color:#c22e2e}
.where{display:flex;gap:8px;margin:0 0 6px}
.where button{flex:1;font-weight:500}
.where button[aria-pressed=true]{background:#08733f;color:#fff}
.where button[aria-pressed=false]{background:#fff;color:#17211b;border:1px solid #d9dfdb}
.warn{background:#fdf7e8;color:#8a5f06;padding:10px 12px;border-radius:8px;
font-size:.85rem;margin-bottom:12px}
pre{background:#f7f8f7;padding:14px;border-radius:8px;overflow-x:auto;font-size:.78rem;
margin:0 0 10px;max-height:220px;line-height:1.5}
.dim{opacity:.45;pointer-events:none}
.steps{counter-reset:s;margin:0 0 14px;padding-left:20px;font-size:.88rem;color:#66706a}
.steps li{margin-bottom:4px}
#now{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 8px}
#now span{font-size:.8rem;padding:4px 10px;border-radius:999px;background:#eef1ef;color:#3c4642}
#now span.on{background:#e1f1e8;color:#075a33}
#now span.live{background:#fdf7e8;color:#8a5f06;font-weight:600}
#now span.off{background:#fff3f2;color:#c22e2e}
#todo{font-size:.85rem;color:#66706a;margin:0 0 24px}
</style></head><body>

<h1>자동매매 설정</h1>
<p class="sub">여기서 다 끝납니다. 파일을 직접 열 필요 없어요.</p>

<div id="now"></div>
<p id="todo"></p>

<section id="s1">
  <h2><b>1</b> NH 키 넣기 <small id="k-state"></small></h2>
  <p class="help">NH 나무 PLUG에서 앱을 만들면 받는 두 값입니다.
    모의투자와 실제 계좌가 <b>같은 키</b>를 씁니다.
    <a href="https://www.nhplug.com" target="_blank" rel="noreferrer">NH PLUG 열기</a></p>
  <label><span>APP KEY</span><input type="password" id="key" autocomplete="off" placeholder="붙여넣기"></label>
  <label><span>APP SECRET</span><input type="password" id="secret" autocomplete="off" placeholder="붙여넣기"></label>

  <p class="help" style="margin-bottom:6px">어느 계좌로 주문할까요?</p>
  <div class="where">
    <button type="button" id="m-mock" aria-pressed="true" onclick="setMock(1)">모의투자 계좌</button>
    <button type="button" id="m-live" aria-pressed="false" onclick="setMock(0)">실제 계좌</button>
  </div>
  <div id="live-warn" class="warn" hidden>실제 돈으로 주문이 나갑니다. 모의투자로 며칠 확인한 뒤에 바꾸세요.
    아래 <b>3단계 Telegram 연결</b>을 반드시 끝내야 주문이 나갑니다.</div>

  <button id="save" onclick="save()">저장하고 연결 확인</button>
  <div id="m1" class="msg" hidden></div>
</section>

<section id="s2" class="dim">
  <h2><b>2</b> Codex와 상담해서 전략 만들기</h2>
  <p class="help"><b>Codex와 대화하던 중이라면</b> 그 창으로 돌아가 <b>“연결됐다”</b> 라고
    말하면 됩니다. Codex가 이어서 하나씩 물어보고, 답을 다 들으면
    <code>strategy.py</code>를 고쳐 줍니다. 여기서는 끝나고 <b>전략 검사</b>만 누르세요.</p>
  <details style="margin-bottom:12px">
    <summary style="cursor:pointer;font-size:.9rem">Codex를 직접 열어서 할래요 (프롬프트 복사)</summary>
    <p class="help" style="margin-top:10px">이 폴더에서 Codex를 열고 아래를 붙여넣으세요.</p>
    <pre id="prompt"></pre>
    <button onclick="copyPrompt()" id="cp-btn">Codex에 붙여넣을 내용 복사</button>
  </details>
  <button class="ghost" onclick="checkStrategy()" id="ck-btn">전략 검사</button>
  <div id="m2" class="msg" hidden></div>
</section>

<section id="s3" class="dim">
  <h2><b>3</b> Telegram 승인 연결 <small id="t-state">모의투자만 하면 건너뛰어도 돼요</small></h2>
  <p class="help">실제 돈으로 주문할 때는 <b>Telegram에서 한 번 승인</b>해야 나갑니다.
    승인하지 않으면 주문이 나가지 않습니다. 모의투자만 쓸 거면 건너뛰어도 됩니다.</p>
  <ol class="steps">
    <li>Telegram에서 <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">@BotFather</a>를 열고 <code>/newbot</code> 으로 봇을 만듭니다</li>
    <li>받은 토큰을 아래에 붙여넣습니다</li>
    <li>나타나는 링크를 눌러 봇 대화창에서 <b>시작</b>을 누릅니다</li>
  </ol>
  <label><span>봇 토큰</span><input type="password" id="tgtoken" autocomplete="off" placeholder="123456:ABC-..."></label>
  <button onclick="tgToken()" id="tt-btn">토큰 확인</button>
  <div id="tglink" hidden style="margin-top:12px">
    <a id="tgurl" href="#" target="_blank" rel="noreferrer" style="display:block;margin-bottom:8px"></a>
    <button class="ghost" onclick="tgLink()" id="tl-btn">봇에서 시작을 눌렀어요</button>
  </div>
  <div id="m4" class="msg" hidden></div>
</section>

<section id="s4" class="dim">
  <h2><b>4</b> 시작 — Codex에 예약 만들기</h2>
  <p class="help">터미널에 프로그램을 띄워 놓지 않습니다. <b>Codex 앱 → 예약</b>에서
    <b>1시간 간격</b>으로 새 작업을 만들고, 아래 내용을 그대로 넣으세요.
    실행 위치는 <b>이 기기</b>로 둡니다.</p>
  <pre id="cmd">%%SCHEDULE%%</pre>
  <p class="help">장이 닫혀 있으면 <code>--scan</code>이 곧바로 끝납니다.
    멈추고 싶으면 예약을 <b>일시 중지</b>하면 됩니다.</p>
  <button class="ghost" onclick="dryrun()" id="d-btn">먼저 한 번만 확인해보기 (주문 안 함)</button>
  <div id="m3" class="msg" hidden></div>
</section>

<script>
let mock = 1;
const PROMPT = %%PROMPT%%;
document.getElementById('prompt').textContent = PROMPT;

function setMock(v){
  mock = v;
  document.getElementById('m-mock').setAttribute('aria-pressed', v ? 'true':'false');
  document.getElementById('m-live').setAttribute('aria-pressed', v ? 'false':'true');
  document.getElementById('live-warn').hidden = !!v;
  // 실제 계좌면 Telegram 연결이 선택이 아니라 필수입니다.
  document.getElementById('t-state').textContent =
    v ? '모의투자만 하면 건너뛰어도 돼요' : '실제 계좌라 반드시 연결해야 해요';
}
function show(id, text, ok){
  const el = document.getElementById(id);
  el.hidden = false; el.textContent = text;
  el.className = 'msg ' + (ok ? 'ok' : 'err');
}
async function post(path, body){
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)});
  return r.json();
}
// 지금 무엇이 되어 있고 무엇이 남았는지를 맨 위에 늘 보여 줍니다.
async function refresh(){
  const out = await post('/status', {});
  if (!out.ok) return;
  const s = JSON.parse(out.message);
  const chip = (text, cls) => `<span class="${cls||''}">${text}</span>`;
  document.getElementById('now').innerHTML =
    chip(s.keys ? 'NH 키 연결됨' : 'NH 키 없음', s.keys ? 'on' : 'off') +
    chip(s.live ? '실제 계좌' : '모의투자', s.live ? 'live' : 'on') +
    chip(s.telegram ? 'Telegram 연결됨' : 'Telegram 안 됨',
         s.telegram ? 'on' : (s.live ? 'off' : ''));
  let todo = '';
  if (!s.keys) todo = '아래 1단계에서 NH 키를 넣어 주세요.';
  else if (s.blocked) todo = '실제 계좌인데 Telegram이 없어 주문이 한 건도 나가지 않습니다. ' +
    '아래 3단계에서 연결해 주세요.';
  else if (s.live) todo = '실제 돈으로 주문이 나갑니다. 주문마다 Telegram으로 확인을 보냅니다.';
  else todo = '모의투자입니다. 가짜 돈이라 승인 없이 바로 주문합니다. ' +
    '실제 계좌로 바꾸려면 3단계 Telegram을 먼저 연결하세요.';
  document.getElementById('todo').textContent = todo;
  if (s.keys) for (const id of ['s2','s3','s4']) document.getElementById(id).classList.remove('dim');
  if (s.keys) document.getElementById('k-state').textContent = '연결됨';
  if (s.telegram) document.getElementById('t-state').textContent = '연결됨';
  setMock(s.live ? 0 : 1);
}
refresh();
async function save(){
  const btn = document.getElementById('save');
  btn.disabled = true; btn.textContent = '연결 확인 중…';
  const out = await post('/save', {key: key.value.trim(), secret: secret.value.trim(), mock});
  btn.disabled = false; btn.textContent = '저장하고 연결 확인';
  show('m1', out.message, out.ok);
  await refresh();
}
async function copyPrompt(){
  const btn = document.getElementById('cp-btn');
  try { await navigator.clipboard.writeText(PROMPT); }
  catch (e) {
    // 클립보드 권한이 없으면 직접 고르실 수 있게 선택해 드립니다.
    const r = document.createRange(); r.selectNode(document.getElementById('prompt'));
    getSelection().removeAllRanges(); getSelection().addRange(r);
    btn.textContent = '위 내용을 직접 복사해 주세요 (Ctrl+C)'; return;
  }
  btn.textContent = '복사했습니다. Codex에 붙여넣으세요';
  setTimeout(() => { btn.textContent = 'Codex에 붙여넣을 내용 복사'; }, 4000);
}
async function checkStrategy(){
  const btn = document.getElementById('ck-btn');
  btn.disabled = true; btn.textContent = '검사 중…';
  const out = await post('/check', {});
  btn.disabled = false; btn.textContent = '전략 검사';
  show('m2', out.message, out.ok);
}
async function tgToken(){
  const btn = document.getElementById('tt-btn');
  btn.disabled = true; btn.textContent = '확인 중…';
  const out = await post('/telegram-token', {token: tgtoken.value.trim()});
  btn.disabled = false; btn.textContent = '토큰 확인';
  if (!out.ok) return show('m4', out.message, false);
  const info = JSON.parse(out.message);
  const a = document.getElementById('tgurl');
  a.href = info.url;
  a.textContent = '@' + info.username + ' 봇 열기 → 시작 누르기';
  document.getElementById('tglink').hidden = false;
  show('m4', '봇을 찾았습니다. 위 링크를 눌러 대화창에서 시작을 누른 뒤, 아래 버튼을 눌러 주세요.', true);
}
async function tgLink(){
  const btn = document.getElementById('tl-btn');
  btn.disabled = true; btn.textContent = '연결 확인 중… (최대 3분)';
  const out = await post('/telegram-link', {});
  btn.disabled = false; btn.textContent = '봇에서 시작을 눌렀어요';
  show('m4', out.message, out.ok);
  if (out.ok){
    await refresh();
    // 여기까지 왔으면 실제 계좌로 바꿀 수 있습니다. 다음에 뭘 하면 되는지 알려 줍니다.
    show('m4', out.message + '\\n\\n이제 1단계에서 [실제 계좌]를 고르고 저장하면 실거래로 바뀝니다.', true);
  }
}
async function dryrun(){
  const btn = document.getElementById('d-btn');
  btn.disabled = true; btn.textContent = '확인 중… (1분쯤)';
  const out = await post('/dryrun', {});
  btn.disabled = false; btn.textContent = '먼저 한 번만 돌려보기 (주문 안 함)';
  show('m3', out.message, out.ok);
}
</script></body></html>
"""


def update_env(**values):
    """.env의 항목만 갱신합니다. 사용자가 편집기를 열 일이 없게 하는 게 목적입니다.

    통째로 덮어쓰면 먼저 연결해 둔 Telegram 값이 지워지므로 항목 단위로 씁니다.
    """
    lines = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep:
                lines[name.strip()] = value
    lines.update({key: str(value) for key, value in values.items()})
    ENV.write_text("".join(f"{k}={v}\n" for k, v in lines.items()), encoding="utf-8")


def run_child(args, timeout=300):
    """자식 파이썬 프로세스 실행.

    부모에 남아 있는 NHPLUG_* 를 물려주면 방금 저장한 .env 대신 옛 키로 붙어서,
    틀린 키를 넣어도 "연결됨"이 나옵니다.
    """
    clean = {k: v for k, v in os.environ.items() if not k.startswith("NHPLUG_")}
    # Windows의 기본 콘솔 인코딩(CP949)을 UTF-8로 잘못 읽으면 검사·프리뷰의
    # 한국어가 전부 깨집니다. 자식 프로세스가 처음부터 UTF-8로 쓰게 맞춥니다.
    clean["PYTHONIOENCODING"] = "utf-8"
    clean["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, *args],
        cwd=HERE,
        env=clean,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def check_connection(mock):
    """방금 넣은 키로 진짜 붙는지 확인합니다."""
    code = "import broker;a=broker.account();print('OK', a[:3]+'***'+a[-2:], broker.cash(a))"
    result = run_child(["-c", code], timeout=120)
    out = (result.stdout or "").strip()
    if result.returncode == 0 and out.startswith("OK"):
        _, masked, cash = out.split(None, 2)
        where = "모의투자" if mock else "실제"
        # 계좌번호는 언제나 가립니다. 잔고는 본인 화면이라 그대로 보여 줍니다.
        return True, f"연결됐습니다.\n{where} 계좌 {masked} · 주문가능 현금 {int(cash):,}원"
    lines = [line for line in (result.stderr or out or "").strip().splitlines() if line.strip()]
    tail = lines[-1] if lines else "알 수 없는 오류"
    if "AppKey" in tail or "인증" in tail or "auth" in tail.lower():
        return False, f"키가 맞지 않는 것 같습니다.\n{tail}"
    if "계좌를 찾지 못했습니다" in tail:
        return False, tail
    return False, f"연결하지 못했습니다.\n{tail}"


def current_state():
    """지금 무엇이 되어 있고 무엇이 남았는가. 화면 맨 위에 그대로 보여 줍니다.

    "Telegram을 연결하세요"라고만 하면 어디서 어떻게 하는지 알 수가 없습니다.
    지금 상태를 먼저 보여 주고, 남은 것을 짚어 주는 편이 덜 막막합니다.
    """
    saved = dotenv_values(ENV)

    def has(*names):
        return all(str(saved.get(name, "")).strip() for name in names)

    live = str(saved.get("NH_MOCK", "1")).strip() == "0"
    telegram_on = has("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    return {
        "keys": has("NHPLUG_APP_KEY", "NHPLUG_APP_SECRET"),
        "live": live,
        "telegram": telegram_on,
        # 실거래인데 Telegram이 없으면 주문이 한 건도 나가지 않습니다. 조용히
        # 멈추는 대신 화면에서 미리 알려 줍니다.
        "blocked": live and not telegram_on,
    }


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 브라우저 요청 로그로 화면을 채우지 않습니다.

    def _send(self, body, kind="application/json", status=200, cookie=None):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{kind}; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        if cookie:
            self.send_header("Set-Cookie", f"nh_setup={cookie}; Path=/; SameSite=Strict")
        self.end_headers()
        self.wfile.write(raw)

    def allowed(self):
        """127.0.0.1로 열었으면 누구나(=나만) 씁니다.

        --public 으로 열었을 때만 열쇠말을 받습니다. 이 화면은 .env를 고치고
        파이썬을 실행하므로, 바깥에 열어 둔 채 아무나 들어오게 두면 안 됩니다.
        """
        token = getattr(self.server, "token", None)
        if not token:
            return True
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        given = query.get("t", [""])[0] or self._cookie_token()
        # 바이트로 비교합니다. 한글 같은 글자가 섞여 들어와도 예외 대신 403이어야
        # 합니다(compare_digest는 비ASCII 문자열을 받지 않습니다).
        return secrets.compare_digest(given.encode("utf-8"), token.encode("utf-8"))

    def _cookie_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name == "nh_setup":
                return value
        return ""

    def do_GET(self):
        if not self.allowed():
            return self._send("주소 끝의 열쇠말이 없거나 틀렸습니다.", "text/plain", 403)
        # 누군가 화면을 열었다는 표시. 열렸으면 "이렇게 접속하세요" 안내를 더
        # 뿌리지 않습니다.
        self.server.opened = True
        page = PAGE.replace("%%PROMPT%%", json.dumps(CODEX_PROMPT, ensure_ascii=False))
        # 예약에 넣을 글은 schedule.txt 한 곳에만 둡니다. 화면과 README가 따로
        # 적혀 있으면 언젠가 서로 어긋납니다.
        page = page.replace("%%SCHEDULE%%", schedule_text())
        # 열쇠말을 쿠키로 옮겨 둡니다. 이후 버튼(POST)마다 주소에 붙이지 않아도
        # 되고, 주소창을 실수로 복사해 남길 일도 줄어듭니다.
        self._send(page, "text/html", cookie=getattr(self.server, "token", None))

    def do_POST(self):
        if not self.allowed():
            return self._send(json.dumps({"ok": False, "message": "다시 접속해 주세요."}), status=403)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(json.dumps({"ok": False, "message": "요청을 읽지 못했습니다."}))
        route = urllib.parse.urlparse(self.path).path
        handler = {
            "/save": self.save,
            "/status": self.status,
            "/check": self.check,
            "/dryrun": self.dryrun,
            "/telegram-token": self.telegram_token,
            "/telegram-link": self.telegram_link,
        }.get(route)
        if not handler:
            return self._send(json.dumps({"ok": False, "message": "알 수 없는 요청입니다."}))
        try:
            ok, message = handler(body)
        except Exception as exc:  # 어떤 실패든 화면에 한 줄로 보여 줍니다.
            ok, message = False, f"{type(exc).__name__}: {exc}"
        self._send(json.dumps({"ok": ok, "message": message}, ensure_ascii=False))

    def save(self, body):
        key, secret = body.get("key", "").strip(), body.get("secret", "").strip()
        if not key or not secret:
            return False, "APP KEY와 APP SECRET을 모두 넣어 주세요."
        mock = bool(body.get("mock", 1))

        # 실거래인데 Telegram이 없으면 주문이 한 건도 안 나갑니다. 저장해 놓고
        # 나중에 조용히 멈추게 두는 대신, 여기서 막고 무엇을 하면 되는지 알려 줍니다.
        # 키는 모의투자로 저장해 두어 처음부터 다시 넣지 않아도 됩니다.
        if not mock and not current_state()["telegram"]:
            update_env(NHPLUG_APP_KEY=key, NHPLUG_APP_SECRET=secret, NH_MOCK=1)
            return False, (
                "Telegram을 먼저 연결해야 실제 계좌로 바꿀 수 있습니다.\n"
                "승인 없이 실제 돈이 나가는 길을 두지 않기 때문입니다.\n\n"
                "아래 3단계에서 봇을 연결한 뒤, 다시 [실제 계좌]를 고르고 저장해 주세요.\n"
                "키는 모의투자로 저장해 뒀으니 다시 넣지 않아도 됩니다."
            )

        update_env(
            NHPLUG_APP_KEY=key, NHPLUG_APP_SECRET=secret, NH_MOCK=1 if mock else 0
        )
        return check_connection(mock)

    def status(self, _body):
        """화면 맨 위 상태 줄. 열 때마다 새로 읽습니다."""
        return True, json.dumps(current_state())

    def telegram_token(self, body):
        """봇 토큰을 확인하고, 사용자가 눌러서 연결할 링크를 돌려줍니다."""
        import telegram

        token = body.get("token", "").strip()
        if not token:
            return False, "BotFather에서 받은 토큰을 넣어 주세요."
        try:
            username = telegram.verify_token(token)
        except Exception as exc:
            return False, f"토큰을 확인하지 못했습니다.\n{exc}"
        code = telegram.link_code()
        self.server.pending_link = (token, code)
        return True, json.dumps(
            {"username": username, "url": f"https://t.me/{username}?start={code}"}
        )

    def telegram_link(self, _body):
        """사용자가 봇에게 /start 를 보낼 때까지 기다렸다 채팅을 저장합니다."""
        import telegram

        pending = getattr(self.server, "pending_link", None)
        if not pending:
            return False, "먼저 봇 토큰을 확인해 주세요."
        token, code = pending
        chat_id = telegram.wait_for_link(token, code, timeout=170)
        if not chat_id:
            return False, "연결을 확인하지 못했습니다. 봇 대화창에서 시작을 누른 뒤 다시 눌러 주세요."
        update_env(TELEGRAM_BOT_TOKEN=token, TELEGRAM_CHAT_ID=chat_id)
        self.server.pending_link = None
        return True, (
            f"연결됐습니다. 채팅 {chat_id[:3]}***{chat_id[-2:]}\n"
            "이제 실거래 주문은 여기로 확인을 보냅니다."
        )

    def check(self, _body):
        result = run_child(["check.py"], timeout=60)
        out = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, out or "출력이 없습니다."

    def dryrun(self, _body):
        result = run_child(["trade.py", "--preview"])
        out = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, out[-1500:] or "출력이 없습니다."


def free_port(host, preferred=8777):
    for candidate in (preferred, 0):
        with socket.socket() as probe:
            try:
                probe.bind((host, candidate))
                return probe.getsockname()[1]
            except OSError:
                continue
    raise SystemExit("빈 포트를 찾지 못했습니다.")


def has_browser():
    """이 컴퓨터에서 브라우저를 띄울 수 있는가.

    서버(SSH로 들어온 리눅스)에는 브라우저가 없습니다. 그런데도 열었다고 말하면
    사용자는 열리지 않는 127.0.0.1을 하염없이 기다리게 됩니다.
    """
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        return False
    try:
        webbrowser.get()
        return True
    except webbrowser.Error:
        return False


def ssh_peer():
    """SSH로 들어와 있다면 (내 PC 주소, 이 서버 주소). 아니면 (None, None)."""
    parts = (os.environ.get("SSH_CONNECTION") or "").split()
    return (parts[0], parts[2]) if len(parts) >= 4 else (None, None)


def my_address():
    """안내문에 쓸 이 서버의 주소. 바깥으로 나가는 소켓의 내 쪽 주소를 봅니다."""
    _, here = ssh_peer()
    if here:
        return here
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 53))  # 실제로 패킷이 나가지는 않습니다
            return probe.getsockname()[0]
    except OSError:
        return "서버주소"


def ufw(*args):
    """방화벽 명령 한 번. ufw가 없거나 권한이 없으면 None."""
    if shutil.which("ufw") is None:
        return None
    command = ["ufw", *args]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        command = ["sudo", "-n", *command]
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None


def firewall_open(port, only_from=None):
    """켜져 있는 ufw에 이 포트를 잠깐 엽니다. 되돌릴 규칙을 돌려줍니다.

    사용자가 방화벽 명령을 외우게 하지 않으려는 것입니다. 열어 둔 채 잊어버리는
    쪽이 더 위험하므로, 끝날 때 같은 규칙을 반드시 지웁니다(firewall_close).
    """
    status = ufw("status")
    if status is None or status.returncode != 0:
        return None
    if "Status: active" not in (status.stdout or ""):
        return None  # 방화벽이 꺼져 있으면 건드릴 것이 없습니다.
    rule = (
        ["allow", "from", only_from, "to", "any", "port", str(port), "proto", "tcp"]
        if only_from
        else ["allow", f"{port}/tcp"]
    )
    done = ufw(*rule)
    return rule if done is not None and done.returncode == 0 else None


def firewall_close(rule):
    if rule:
        ufw("delete", *rule)


# 에이전트가 포트를 이어 주기까지 주는 시간. 사람이 브라우저를 여는 시간까지
# 넉넉히 기다립니다. 급하게 대체 안내를 뿌리면 안 하느니만 못합니다.
WAIT_BEFORE_MANUAL = 90


def after(seconds, action):
    """잠시 뒤에 한 번 실행합니다. 프로그램이 끝나는 것을 붙잡지 않습니다."""
    timer = threading.Timer(seconds, action)
    timer.daemon = True
    timer.start()
    return timer


USAGE = """python setup.py            내 컴퓨터에서 (브라우저가 저절로 열립니다)
python setup.py --public   서버에서, SSH 터널을 쓸 수 없을 때만
    --port 8777            쓸 포트
    --minutes 30           이 시간이 지나면 스스로 닫습니다"""


def parse_args(argv):
    opts = {"public": False, "port": 8777, "minutes": 30}
    rest = iter(argv)
    for arg in rest:
        if arg == "--public":
            opts["public"] = True
        elif arg in ("--port", "--minutes"):
            try:
                opts[arg[2:]] = int(next(rest, ""))
            except ValueError:
                raise SystemExit(f"{arg} 뒤에는 숫자를 적어 주세요.")
        elif arg in ("-h", "--help"):
            raise SystemExit(USAGE)
        else:
            raise SystemExit(f"모르는 옵션입니다: {arg}\n\n{USAGE}")
    return opts


def agent_guide(port):
    """서버에서 실행됐을 때 맨 처음 나오는 글.

    이 글을 읽는 것은 사람이 아니라 에이전트(Codex 등)입니다. 사람은 터미널을
    쓸 줄 모릅니다. 그러니 여기에 사람이 칠 명령을 적어 두면 안 됩니다. 적어 두면
    에이전트가 그걸 그대로 사용자에게 옮겨 붙이고, 사용자는 막힙니다.
    에이전트에는 대개 포트를 이어 주는 기능(웹 미리보기)이 있으니 그것을 시킵니다.
    """
    return (
        f"설정 화면이 이 컴퓨터의 127.0.0.1:{port} 에 떠 있습니다.\n"
        f"FORWARD_PORT={port}\n"
        "\n"
        "─ 이 글을 읽는 에이전트에게 ────────────────────────────────\n"
        "사용자는 터미널을 쓰지 않습니다. 명령줄을 사용자에게 보여 주지 마세요.\n"
        f"당신의 포트 전달 기능(웹 미리보기 / port forward)으로 {port} 번을 열고,\n"
        "열린 주소 한 줄만 사용자에게 건네주세요. 사용자는 그 주소에서 키를 넣습니다.\n"
        "키는 묻지도, 대신 넣지도 마세요. 이 프로세스는 끄지 말고 켜 두세요.\n"
        "────────────────────────────────────────────────────────\n"
    )


def manual_guide(port):
    """아무도 화면을 열지 못했을 때만 뒤늦게 나오는 최후의 수단.

    포트를 이어 줄 방법이 정말 없는 경우에만 쓰라고, 처음부터 보여 주지 않습니다.
    """
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "root"
    return (
        f"\n아직 아무도 설정 화면({port}번)을 열지 않았습니다.\n"
        "에이전트에게 포트 전달 기능이 없을 때만, 그때만 아래를 쓰세요.\n"
        "\n"
        "  ① 사용자 PC에서 한 줄:\n"
        f"     ssh -N -L {port}:127.0.0.1:{port} {user}@{my_address()}\n"
        f"  ② 사용자 PC 브라우저에서 http://127.0.0.1:{port}\n"
        "\n"
        "  또는 이 컴퓨터에서 다시: python setup.py --public\n"
    )


def public_guide(url, port, minutes, rule, only_from):
    who = f"{only_from} 에서만" if only_from else "아무 주소에서나"
    lines = [
        "설정 화면을 이 서버 주소로 잠깐 열었습니다. 아래 주소로 접속하세요.",
        "",
        f"     {url}",
        "",
        "주소 끝의 열쇠말까지 통째로 복사해야 열립니다.",
        f"{minutes}분이 지나면 스스로 닫습니다. 다 끝냈으면 Ctrl+C 로 바로 닫아 주세요.",
    ]
    if rule:
        lines.append(f"방화벽(ufw)은 이 포트를 {who} 열어 두었고, 닫을 때 되돌립니다.")
    else:
        lines += [
            "",
            "열리지 않으면 방화벽이 막고 있는 것입니다. 서버에서 한 줄:",
            f"     sudo ufw allow {port}/tcp",
            "DigitalOcean은 웹 화면의 Networking → Firewalls 도 함께 봐야 합니다.",
        ]
    lines += [
        "",
        "※ 이 길은 암호화되지 않은 http 입니다. 키를 넣는 잠깐만 열어 두세요.",
        "  가능하면 SSH 터널(python setup.py)을 쓰는 편이 안전합니다.",
    ]
    return "\n".join(lines)


def main():
    opts = parse_args(sys.argv[1:])
    host = "0.0.0.0" if opts["public"] else "127.0.0.1"
    port = free_port(host, opts["port"])
    server = http.server.HTTPServer((host, port), Handler)
    server.opened = False
    only_from, rule = None, None

    if opts["public"]:
        # 바깥에 열면 열쇠말을 붙입니다. 그리고 들어온 SSH 주소를 알면 그 주소만
        # 열어 둡니다. 클라우드 서버의 열린 포트는 몇 분 만에 스캔당합니다.
        server.token = secrets.token_urlsafe(9)
        only_from, _ = ssh_peer()
        rule = firewall_open(port, only_from)
        url = f"http://{my_address()}:{port}/?t={server.token}"
        print(public_guide(url, port, opts["minutes"], rule, only_from))
        after(opts["minutes"] * 60, server.shutdown)
    elif has_browser():
        url = f"http://127.0.0.1:{port}"
        after(0.5, lambda: webbrowser.open(url))
        print(f"설정 화면을 열었습니다: {url}")
        print("다 끝나면 이 터미널에서 Ctrl+C 를 누르세요.")
    else:
        print(agent_guide(port))
        # 대개는 에이전트가 알아서 포트를 이어 줍니다. 그러면 이 아래는 영영
        # 나오지 않습니다. 정말 아무도 못 열었을 때만 뒤늦게 한 번 알립니다.
        after(WAIT_BEFORE_MANUAL, lambda: print(manual_guide(port)) if not server.opened else None)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        firewall_close(rule)
        print("\n설정을 마쳤습니다." + (" 열었던 포트는 닫았습니다." if rule else ""))


if __name__ == "__main__":
    main()
