"""strategy.py가 제대로 돌아가는지 검사합니다. `python check.py`

Codex가 전략을 고친 뒤 이걸 돌려서 확인합니다. 여기서 막으면 장중에 안 터집니다.
통과하면 종료코드 0, 실패하면 1입니다.
"""

import ast
import sys
from pathlib import Path

from dotenv import load_dotenv

# 남이 .env를 불러 줬기를 기대하지 않습니다. 이 파일만 단독으로 써도 맞아야 합니다.
ENV = Path(__file__).with_name(".env")
load_dotenv(ENV, override=True)

STRATEGY = Path(__file__).parent / "strategy.py"

# 계산에 쓰는 표준 라이브러리는 넓게 열어 둡니다. 막는 것은 파일·네트워크·프로세스에
# 손대는 것뿐입니다(os, sys, pathlib, io, socket, urllib, subprocess, importlib …).
# 전략은 숫자를 보고 판단만 하면 되고, 바깥 세상과 이야기할 일이 없습니다.
SAFE_IMPORTS = {
    "array", "base64", "binascii", "bisect", "calendar", "cmath", "collections",
    "colorsys", "copy", "dataclasses", "datetime", "decimal", "difflib", "enum",
    "fractions", "functools", "graphlib", "hashlib", "heapq", "hmac", "itertools",
    "json", "math", "numbers", "operator", "queue", "random", "re", "secrets",
    "statistics", "string", "struct", "textwrap", "time", "types", "typing",
    "unicodedata", "uuid", "zoneinfo",
}
FORBIDDEN_CALLS = {
    "__import__", "breakpoint", "compile", "delattr", "eval", "exec", "getattr",
    "globals", "input", "locals", "open", "setattr", "vars",
}


def validate_source(source):
    """전략이 파일·네트워크에 손대지 않는 계산 코드인지 먼저 확인합니다."""
    tree = ast.parse(source, filename="strategy.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [item.name.split(".", 1)[0] for item in node.names]
            blocked = [name for name in modules if name not in SAFE_IMPORTS]
            if blocked:
                raise ValueError(f"허용하지 않는 import입니다: {', '.join(blocked)}")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".", 1)[0]
            if node.level or module not in SAFE_IMPORTS:
                raise ValueError(f"허용하지 않는 import입니다: {node.module or '(상대 경로)'}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                raise ValueError(f"전략에서 {node.func.id}()를 사용할 수 없습니다")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("전략에서 내부 속성(__...)에 접근할 수 없습니다")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("전략에서 내부 이름(__...)에 접근할 수 없습니다")
    return compile(tree, "strategy.py", "exec")


# 국내는 원, 미국은 달러 기준으로 넉넉한 값을 기본으로 둡니다.
_KR = {"market": "kr", "currency": "KRW", "turnover": 5_000_000_000_000,
       "high_52w": 374500, "low_52w": 67500, "per": 9.6, "pbr": 3.7,
       "market_cap": 16_000_000_000_000, "industry": "코스피 전기·전자"}
_US = {"market": "us", "currency": "USD", "turnover": 8_000_000_000,
       "high_52w": 340.08, "low_52w": 224.9, "per": 36.2, "pbr": None,
       "market_cap": None, "industry": "컴퓨터"}

# 사고팔지는 Codex가 정합니다. 그 답이 왔을 때와 못 받았을 때를 모두 넣어 봅니다.
_BUY = {"decision": "buy",
        "reason": "현재가 71,000원이 5일 평균 70,400원 위, MACD 120이 신호선 95 위입니다"}
_SELL = {"decision": "sell",
         "reason": "5일 평균 71,800원 아래로 내려왔고 MACD 40이 신호선 78 아래로 꺾였습니다"}
_HOLD = {"decision": "hold", "reason": "RSI 72로 과열 구간이라 새로 사지 않습니다"}

# 보유/미보유, 오르는 장/내리는 장, 국내/미국, 자료가 없을 때까지 모두 넣어 봅니다.
CASES = [
    ("국내 사라함", {**_KR, "held": False, "price": 71000, "qty": 0, "avg": 0, "pnl_pct": 0.0,
                 "ai": _BUY}),
    ("국내 두랬함", {**_KR, "held": False, "price": 71000, "qty": 0, "avg": 0, "pnl_pct": 0.0,
                 "ai": _HOLD}),
    ("국내 팔라함", {**_KR, "held": True, "price": 72000, "qty": 5, "avg": 71000,
                 "pnl_pct": 1.4, "ai": _SELL}),
    # Codex가 뭐라 하든 손절·익절 선은 규칙이 지킵니다. 여기서는 hold라고 답해도 팔아야 합니다.
    ("국내 큰 손실", {**_KR, "held": True, "price": 60000, "qty": 5, "avg": 71000,
                  "pnl_pct": -15.5, "ai": _HOLD}),
    ("국내 큰 이익", {**_KR, "held": True, "price": 85000, "qty": 5, "avg": 71000,
                  "pnl_pct": 19.7, "ai": _HOLD}),
    # 사라고 해도 거를 것은 걸러야 합니다.
    ("국내 거래한산", {**_KR, "held": False, "price": 71000, "qty": 0, "avg": 0,
                  "pnl_pct": 0.0, "turnover": 1_000_000, "ai": _BUY}),
    ("국내 고점부근", {**_KR, "held": False, "price": 374000, "qty": 0, "avg": 0,
                  "pnl_pct": 0.0, "ai": _BUY}),
    # Codex가 없거나 답이 이상한 날. 모르는 상태를 "괜찮다"로 읽으면 안 됩니다.
    ("국내 판단없음", {**_KR, "held": False, "price": 71000, "qty": 0, "avg": 0,
                  "pnl_pct": 0.0, "ai": None}),
    ("보유중 판단없음", {**_KR, "held": True, "price": 72000, "qty": 5, "avg": 71000,
                   "pnl_pct": 1.4, "ai": None}),
    ("미국 미보유", {**_US, "held": False, "price": 305.77, "qty": 0, "avg": 0, "pnl_pct": 0.0,
                 "ai": _BUY}),
    ("미국 보유", {**_US, "held": True, "price": 280.0, "qty": 2, "avg": 305.0,
                "pnl_pct": -8.2, "ai": _HOLD}),
    # 시세 일부가 비어서 온 날. None을 0으로 읽으면 여기서 터지거나 잘못 삽니다.
    ("미국 조회실패", {**_US, "held": False, "price": 305.77, "qty": 0, "avg": 0, "pnl_pct": 0.0,
                  "ai": _BUY, "turnover": None, "high_52w": None, "low_52w": None,
                  "per": None}),
]


def fail(message):
    print(f"실패: {message}")
    sys.exit(1)


def main():
    namespace = {}
    try:
        code = validate_source(STRATEGY.read_text(encoding="utf-8"))
        exec(code, namespace)  # noqa: S102
    except Exception as exc:
        fail(f"strategy.py를 불러오지 못했습니다 ({type(exc).__name__}: {exc})")

    for field, kind in (
        ("SYMBOLS", list),
        ("US_SYMBOLS", list),
        ("BUY_AMOUNT", int),
        ("US_BUY_AMOUNT", int),
        ("MAX_HOLDINGS", int),
    ):
        if field not in namespace:
            fail(f"{field}가 없습니다.")
        if not isinstance(namespace[field], kind):
            fail(f"{field}의 형식이 올바르지 않습니다.")

    kr, us = namespace["SYMBOLS"], namespace["US_SYMBOLS"]
    if not kr and not us:
        fail("살펴볼 종목이 하나도 없습니다. 국내나 미국 중 하나는 있어야 합니다.")
    for code in kr:
        if not (isinstance(code, str) and len(code) == 6 and code.isdigit()):
            fail(f"국내 종목코드는 6자리 숫자여야 합니다: {code!r}")
    for ticker in us:
        # BRK.B, BF.B 처럼 점이 들어가는 티커가 실제로 있습니다.
        if not (
            isinstance(ticker, str)
            and ticker == ticker.upper()
            and ticker.replace(".", "").replace("-", "").isalpha()
        ):
            fail(f"미국 티커는 대문자 영문이어야 합니다: {ticker!r}")
    if namespace["MAX_HOLDINGS"] < 1:
        fail("MAX_HOLDINGS는 1 이상이어야 합니다.")
    if namespace["BUY_AMOUNT"] < 1 or namespace["US_BUY_AMOUNT"] < 1:
        fail("한 종목에 넣을 금액은 1 이상이어야 합니다.")
    if not callable(namespace.get("decide")):
        fail("decide 함수가 없습니다.")

    # facts()는 장중에 종목마다 불립니다. 여기서 같이 불러 봐야 터지는지 압니다.
    more = namespace.get("facts")
    more = more if callable(more) else (lambda m: [])

    closes = [69000 + i * 100 for i in range(20)]
    for label, extra in CASES:
        m = {"code": kr[0] if kr else "005930", "name": "테스트", "closes": closes,
             "cash": 5_000_000, "change_pct": 1.2, **extra}
        if extra["market"] == "us":
            m["code"] = us[0] if us else "AAPL"
            m["closes"] = [300 + i * 0.5 for i in range(20)]
        try:
            shown = list(more(m) or [])
        except Exception as exc:
            fail(f"{label}에서 facts()가 터집니다 ({type(exc).__name__}: {exc})")
        if any(not isinstance(line, str) for line in shown):
            fail(f"{label}: facts()는 문자열 리스트를 돌려줘야 합니다.")
        try:
            result = namespace["decide"](m)
        except Exception as exc:
            fail(f"{label}에서 터집니다 ({type(exc).__name__}: {exc})")
        if not (isinstance(result, tuple) and len(result) == 2):
            fail(f"{label}: decide는 (행동, 이유) 두 개를 돌려줘야 합니다.")
        if result[0] not in {"buy", "sell", "hold"}:
            fail(f"{label}: 알 수 없는 행동 {result[0]!r}")
        if not isinstance(result[1], str) or not result[1].strip():
            fail(f"{label}: 이유는 비어 있지 않은 문자열이어야 합니다.")
        print(f"  {label:12} {result[0]:5} · {result[1]}")

    # 시세가 아직 안 쌓였을 때도 터지지 않아야 합니다.
    try:
        empty = {**m, "closes": [], "held": False}
        more(empty)
        namespace["decide"](empty)
    except Exception as exc:
        fail(f"시세가 비었을 때 터집니다 ({type(exc).__name__}: {exc})")

    print()
    print("통과했습니다.")
    print(f"  국내 {', '.join(kr) or '안 함'} · 종목당 {namespace['BUY_AMOUNT']:,}원")
    print(f"  미국 {', '.join(us) or '안 함'} · 종목당 ${namespace['US_BUY_AMOUNT']:,}")
    print(f"  최대 {namespace['MAX_HOLDINGS']}종목")


if __name__ == "__main__":
    main()
