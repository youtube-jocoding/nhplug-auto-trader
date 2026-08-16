"""실거래 주문을 Telegram에서 한 번 승인받습니다.

승인은 딱 한 번의 탭으로 끝납니다. 2단계에서 두 번째 탭이 지켜주던 가격 보호는
두 가지가 대신합니다.
  - 이 앱은 지정가만 보냅니다. 메시지에 적힌 가격보다 불리하게 체결되지 않습니다.
  - 승인 사이에 가격이 불리한 쪽으로 크게 움직였으면 주문하지 않습니다.

토큰과 채팅 연결은 `python setup.py` 화면에서 합니다. 직접 .env를 열 필요 없습니다.
"""

import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ENV = Path(__file__).with_name(".env")
load_dotenv(ENV, override=True)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# 승인 메시지를 본 뒤 이만큼 넘게 불리해지면 주문하지 않습니다.
DRIFT_LIMIT_PCT = 1.0
# 답이 없으면 이 시간이 지나 취소합니다. 다음 확인에서 최신 가격으로 다시 만듭니다.
ANSWER_TIMEOUT = 180

# 본문 마지막 줄. 결과가 정해지면 이 줄만 바꿔서 스크롤해도 상태가 분명하게 합니다.
_WAITING = f"승인하면 바로 전송됩니다. {ANSWER_TIMEOUT // 60}분 안에 답하지 않으면 취소됩니다."

_offset = None  # getUpdates 커서. 같은 버튼을 두 번 처리하지 않기 위해 씁니다.
_used = set()  # 이미 처리한 승인 토큰. 같은 승인으로 두 번 주문할 수 없습니다.
_messages = {}  # 승인 토큰 -> 보낸 메시지. 시간이 지나면 버튼을 지우려고 들고 있습니다.


def configured():
    return bool(TOKEN and CHAT_ID)


def _api(method, payload=None, timeout=30):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(f"Telegram 오류: {body.get('description')}")
    return body.get("result")


def verify_token(token):
    """봇 토큰이 살아 있는지 확인하고 봇 이름을 돌려줍니다. 설정 화면에서 씁니다.

    실패 이유를 초보자가 읽을 수 있는 말로 바꿉니다. "HTTP Error 401"은
    무엇을 고쳐야 하는지 알려주지 않습니다.
    """
    global TOKEN
    saved, TOKEN = TOKEN, token.strip()
    try:
        return _api("getMe").get("username")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError(
                "이 토큰으로는 봇을 찾을 수 없습니다. "
                "BotFather가 보내 준 줄을 통째로 복사했는지 확인해 주세요."
            ) from exc
        raise RuntimeError(f"Telegram에 연결하지 못했습니다 (오류 {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("인터넷 연결을 확인해 주세요.") from exc
    finally:
        TOKEN = saved


def wait_for_link(token, code, timeout=180):
    """사용자가 봇에게 /start <code> 를 보낼 때까지 기다렸다 chat_id를 돌려줍니다.

    채팅방 번호를 사용자가 찾아 입력하지 않아도 되도록, 봇이 받은 메시지에서
    직접 읽습니다.
    """
    global TOKEN, _offset
    saved, TOKEN = TOKEN, token.strip()
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            updates = _api("getUpdates", {"offset": _offset, "timeout": 20}, timeout=40) or []
            for update in updates:
                _offset = update["update_id"] + 1
                message = update.get("message") or {}
                text = str(message.get("text") or "")
                chat = message.get("chat") or {}
                # 개인 채팅에서만 연결합니다. 그룹에 넣으면 다른 사람이 승인할 수 있습니다.
                if code in text and chat.get("type") == "private":
                    return str(chat.get("id"))
        return None
    finally:
        TOKEN = saved


def link_code():
    return secrets.token_urlsafe(8)


def _money(value, currency):
    return f"${value:,.2f}" if currency == "USD" else f"{int(round(value)):,}원"


def ask(order, account):
    """주문안을 보내고 승인 토큰을 돌려줍니다.

    메시지에는 **실제로 나갈 주문 가격**을 그 주문의 통화로 적습니다. 참고용 현재가를
    적으면 사용자가 본 값과 실제 주문 가격이 달라집니다.

    "왜 사는지"가 없으면 사용자는 근거 없이 승인 버튼을 누르게 됩니다. 그래서 판단
    이유를 함께 싣고, 매도일 때는 지금까지의 수익률도 같이 보여 줍니다.
    """
    nonce = secrets.token_urlsafe(12)
    side = "매수" if order["side"] == "buy" else "매도"
    where = "미국" if order["market"] == "us" else "국내"
    total = order["qty"] * order["price"]
    # 같은 종목·같은 수량이 여러 번 오면 어느 것이 지금 살아 있는 주문인지 알 수
    # 없습니다. 짧은 번호와 시각을 붙여 서로 구분되게 합니다.
    order_id = hashlib.sha256(nonce.encode()).hexdigest()[:4].upper()
    lines = [
        f"실거래 주문 확인 — {side}  #{order_id}",
        f"{time.strftime('%m월 %d일 %H:%M')}",
        "",
        f"{order['name']} ({order['code']})",
        f"시장: {where}",
        f"수량: {order['qty']}주",
        f"주문 가격: {_money(order['price'], order['currency'])} 지정가",
        f"주문 금액: {_money(total, order['currency'])}",
    ]
    if order["side"] == "sell" and order.get("pnl_pct") is not None:
        lines.append(f"지금 수익률: {order['pnl_pct']:+.2f}%")
    lines.append(f"계좌: {account[:3]}***{account[-2:]}")
    if order.get("reason"):
        lines += ["", f"왜 {side}하나요?", order["reason"]]
    head = "\n".join(lines)
    text = f"{head}\n\n{_WAITING}"
    sent = _api(
        "sendMessage",
        {
            "chat_id": CHAT_ID,
            "text": text,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {"text": "✅ 승인하고 주문", "callback_data": f"ok:{nonce}"},
                        {"text": "거절", "callback_data": f"no:{nonce}"},
                    ]
                ]
            },
        },
    )
    # 나중에 본문을 고쳐야 하므로 내용을 들고 있습니다. 답글만 달면 위로 스크롤한
    # 사람은 원본의 "승인하면 바로 전송됩니다"만 보고 아직 유효한 줄 압니다.
    _messages[nonce] = {"id": (sent or {}).get("message_id"), "head": head}
    return nonce


def wait(nonce, timeout=ANSWER_TIMEOUT, on_tick=None):
    """승인 버튼을 기다립니다. "approve" / "reject" / None(시간 초과).

    on_tick은 기다리는 동안 남은 시간을 알려 줍니다. 화면이 몇 분 동안 아무 말도
    없으면 사용자는 프로그램이 죽은 줄 압니다.
    """
    global _offset
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if on_tick:
            on_tick(max(0, int(deadline - time.monotonic())))
        try:
            updates = _api("getUpdates", {"offset": _offset, "timeout": 20}, timeout=40) or []
        except (urllib.error.URLError, TimeoutError, RuntimeError):
            continue  # 연결이 잠깐 끊겨도 계속 기다립니다.
        for update in updates:
            _offset = update["update_id"] + 1
            query = update.get("callback_query")
            if not query:
                continue
            data = str(query.get("data") or "")
            message = query.get("message") or {}
            chat = message.get("chat") or {}
            action, _, token = data.partition(":")
            # 등록한 본인 채팅이 아니면 무시합니다. 남이 누른 버튼은 승인이 아닙니다.
            if str(chat.get("id")) != CHAT_ID:
                _answer(query["id"], "이 버튼을 누를 권한이 없습니다.", alert=True)
                continue
            # 기다리는 중인 주문이 아니면 "처리했습니다"라고 하면 안 됩니다. 사용자는
            # 주문이 나간 줄 알게 됩니다. 지난 주문이라는 사실을 분명히 알려 줍니다.
            if token != nonce or token in _used:
                _answer(
                    query["id"],
                    "시간이 지나 취소된 주문입니다. 주문은 나가지 않았습니다.",
                    alert=True,
                )
                # 지난 메시지도 본문을 고쳐 둡니다. 그대로 두면 또 누르게 됩니다.
                _mark_stale(chat.get("id"), message)
                continue
            approved = action == "ok"
            _answer(query["id"], "승인했습니다." if approved else "거절했습니다.")
            # 본문에도 결말을 남깁니다. 나중에 스크롤해도 무엇이 어떻게 됐는지 보입니다.
            resolve(
                token,
                "✅ 승인했습니다. 주문 전 가격을 확인합니다."
                if approved
                else "✖️ 거절해서 주문하지 않았습니다.",
            )
            return "approve" if approved else "reject"
    expire(nonce)
    return None


def resolve(nonce, note):
    """주문의 결말을 본문에 적고 버튼을 없앱니다.

    답글만 달면 위로 스크롤한 사람은 원본의 "승인하면 바로 전송됩니다"만 보고 아직
    유효한 주문이라고 읽습니다. 그래서 마지막 줄 자체를 결과로 바꿉니다.
    """
    saved = _messages.pop(nonce, None)
    if not saved or not saved.get("id"):
        return
    _used.add(nonce)
    try:
        _api(
            "editMessageText",
            {
                "chat_id": CHAT_ID,
                "message_id": saved["id"],
                "text": f"{saved['head']}\n\n{note}",
            },
        )
    except Exception:
        # 본문을 못 고치면 최소한 버튼이라도 없애고 답글로 알립니다.
        _hide_buttons(CHAT_ID, saved["id"])
        _reply(CHAT_ID, saved["id"], note)


def expire(nonce):
    """시간이 지난 주문. 버튼을 없애고 취소됐다고 본문에 적습니다."""
    resolve(nonce, "⏰ 시간이 지나 취소했습니다. 주문은 나가지 않았습니다.")


def _answer(query_id, text, alert=False):
    try:
        _api(
            "answerCallbackQuery",
            {"callback_query_id": query_id, "text": text, "show_alert": alert},
        )
    except Exception:
        pass  # 버튼 응답 실패가 주문 판단을 바꾸지는 않습니다.


def _hide_buttons(chat_id, message_id):
    """누른 버튼을 지웁니다. 같은 메시지를 두 번 누르는 일을 막습니다."""
    try:
        _api(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
        )
    except Exception:
        pass


def _mark_stale(chat_id, message):
    """이미 지난 주문 메시지를 취소됨으로 고칩니다.

    다른 프로세스가 보낸 메시지일 수도 있어 저장해 둔 내용이 없습니다. 콜백이 실어
    주는 원문에서 마지막 안내 줄만 바꿔 씁니다.
    """
    message_id = message.get("message_id")
    body = str(message.get("text") or "").replace(_WAITING, "").rstrip()
    note = "⏰ 시간이 지나 취소했습니다. 주문은 나가지 않았습니다."
    try:
        _api(
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": f"{body}\n\n{note}"},
        )
    except Exception:
        _hide_buttons(chat_id, message_id)


def _reply(chat_id, message_id, text):
    """그 주문 메시지에 답글로 결과를 답니다. 어느 주문 이야기인지 바로 보입니다."""
    try:
        _api(
            "sendMessage",
            {"chat_id": chat_id, "text": text, "reply_to_message_id": message_id},
        )
    except Exception:
        pass  # 알림 실패가 매매를 멈추지는 않습니다.


def price_moved(approved_price, latest_price, side):
    """승인 뒤 가격이 불리한 쪽으로 크게 움직였는가.

    지정가라 체결가는 이미 보호되지만, 오래된 승인이 그대로 나가는 것은 막습니다.
    유리한 방향(매수인데 싸짐, 매도인데 비싸짐)은 그대로 통과시킵니다.
    """
    if approved_price <= 0 or latest_price <= 0:
        return None
    move = (latest_price - approved_price) / approved_price * 100
    adverse = move if side == "buy" else -move
    if adverse <= DRIFT_LIMIT_PCT:
        return None
    direction = "올라" if side == "buy" else "내려"
    return f"승인 뒤 가격이 {abs(move):.2f}% {direction} 주문하지 않았습니다"


def notify(text):
    """결과 알림. 실패해도 매매를 멈추지 않습니다."""
    if not configured():
        return
    try:
        _api("sendMessage", {"chat_id": CHAT_ID, "text": text})
    except Exception:
        pass
