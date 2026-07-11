#!/usr/bin/env python3
"""Atualiza petrol.json com os precos oficiais mensais de combustivel nos UAE.

Corre diariamente via GitHub Actions (equivalente ao combustiveis-dados do LF):
1. Se o mes do JSON != mes atual (hora do Golfo), tenta encontrar os novos
   precos nas fontes abaixo e faz o shift cur->prev + append ao historico.
2. No fim do mes (dia >= 28), tenta apanhar o anuncio do mes seguinte e
   preenche next {dir, note} com os valores anunciados.
3. Caso contrario, calcula a tendencia do Brent (media do mes corrente vs
   media do mes anterior) e preenche next {dir, note} como previsao.

So faz commit quando o JSON muda. Sem dependencias externas (stdlib).
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "petrol.json"

UA = {"User-Agent": "Mozilla/5.0 (compatible; uae-fuel-data-bot; +https://github.com)"}
GULF = timezone(timedelta(hours=4))

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

# Paginas com URL estavel que republicam o anuncio mensal.
# O parser e generico (regex por combustivel + validacao), por isso a ordem
# e apenas preferencia. Acrescenta/remove fontes a vontade.
SOURCES = [
    "https://www.tire.ae/en/blogs/latest-petrol-prices-uae",
    "https://www.dubicars.com/news/petrol-price-in-uae.html",
    "https://wow-rak.com/petrol-prices-for-uae-in-for-this-month/",
    "https://emiratescalculator.com/fuel-price-uae/",
    "https://www.ipt-energy.com/uae/fuel-prices",
]

FUEL_PATTERNS = {
    "s98": r"(?:Super[\s\-]*98|E[\s\-]*Plus[\s\-]*98)",
    "s95": r"(?:Special[\s\-]*95|E[\s\-]*Plus[\s\-]*95)",
    "e91": r"(?:E[\s\-]*Plus[\s\-]*91|EPlus[\s\-]*91|91[\s\-]*octane)",
    "d":   r"(?:Diesel)",
}
# exige casa decimal (3.6, 3.40) para nunca apanhar anos como "2026"
PRICE_RE = r"[^0-9]{0,90}?(\d\.\d{1,2})\b"


def fetch(url, timeout=25):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"  fetch falhou {url}: {e}")
        return ""


def month_label(ym):
    y, m = ym.split("-")
    return f"{MONTHS[int(m) - 1]} {y}"


def shift_month(ym, delta):
    y, m = map(int, ym.split("-"))
    m += delta
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y}-{m:02d}"


def parse_prices(html, ym):
    """Extrai os 4 precos se a pagina mencionar o mes alvo. None se nao der."""
    if not html:
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    label = month_label(ym)
    if not re.search(re.escape(label), text, re.I):
        return None
    out = {}
    for key, fuel_re in FUEL_PATTERNS.items():
        matches = re.findall(fuel_re + PRICE_RE, text, re.I)
        if not matches:
            return None
        vals = [float(v) for v in matches if 1.0 < float(v) < 9.0]
        if not vals:
            return None
        # o primeiro valor plausivel apos o nome do combustivel
        out[key] = vals[0]
    # sanidade: ordem dos octanas e gamas plausiveis
    if not (out["s98"] >= out["s95"] >= out["e91"]):
        return None
    if max(out.values()) / min(out.values()) > 2.5:
        return None
    return {k: round(v, 2) for k, v in out.items()}


def find_prices(ym):
    label = month_label(ym)
    for url in SOURCES:
        print(f"Fonte: {url} (a procurar {label})")
        p = parse_prices(fetch(url), ym)
        if p:
            print(f"  OK: {p}")
            return p
    return None


def brent_series():
    """Fechos diarios do Brent: stooq primeiro, Yahoo como fallback."""
    csv = fetch("https://stooq.com/q/d/l/?s=cb.f&i=d")
    rows = []
    for line in csv.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 5:
            try:
                rows.append((parts[0], float(parts[4])))
            except ValueError:
                pass
    if len(rows) > 20:
        return rows
    raw = fetch("https://query1.finance.yahoo.com/v8/finance/chart/BZ=F?range=3mo&interval=1d")
    try:
        j = json.loads(raw)["chart"]["result"][0]
        ts = j["timestamp"]
        cl = j["indicators"]["quote"][0]["close"]
        return [(datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"), c)
                for t, c in zip(ts, cl) if c]
    except Exception:
        return []


def brent_forecast(now):
    rows = brent_series()
    if not rows:
        return None
    cur_ym = now.strftime("%Y-%m")
    prev_ym = shift_month(cur_ym, -1)
    cur = [c for d, c in rows if d.startswith(cur_ym)]
    prev = [c for d, c in rows if d.startswith(prev_ym)]
    if len(cur) < 3 or len(prev) < 5:
        return None
    a, b = sum(cur) / len(cur), sum(prev) / len(prev)
    pct = (a - b) / b * 100
    nxt = month_label(shift_month(cur_ym, 1))
    if pct >= 1.5:
        return {"dir": "up", "note": f"Brent is averaging ${a:.0f} so far this month, {pct:.0f}% above the previous month - pointing to higher prices in {nxt}."}
    if pct <= -1.5:
        return {"dir": "down", "note": f"Brent is averaging ${a:.0f} so far this month, {abs(pct):.0f}% below the previous month - pointing to lower prices in {nxt}."}
    return {"dir": "stable", "note": f"Brent is averaging ${a:.0f} so far this month, in line with the previous month."}


def main():
    data = json.loads(DATA.read_text())
    before = json.dumps(data, sort_keys=True)
    now = datetime.now(GULF)
    tm = now.strftime("%Y-%m")

    # 1) novo mes em vigor?
    if data["m"] != tm:
        p = find_prices(tm)
        if p:
            if data["m"] == shift_month(tm, -1):
                data["prev"] = data["cur"]
            data["cur"] = p
            data["m"] = tm
            data["updated"] = now.strftime("%Y-%m-%d")
            data["next"] = {"dir": "tbd", "note": ""}
            data["hist"] = [h for h in data["hist"] if h["m"] != tm]
            data["hist"].append({"m": tm, **p})
            data["hist"] = data["hist"][-24:]
        else:
            print("Novo mes ainda sem precos publicados nas fontes.")

    # 2) fim do mes: anuncio do mes seguinte ja saiu?
    announced = None
    if data["m"] == tm and now.day >= 28:
        nm = shift_month(tm, 1)
        announced = find_prices(nm)
        if announced:
            diff = announced["s95"] - data["cur"]["s95"]
            dir_ = "up" if diff >= 0.005 else ("down" if diff <= -0.005 else "stable")
            fils = abs(round(diff * 100))
            word = {"up": "up", "down": "down", "stable": "unchanged"}[dir_]
            note = (f"Announced: Special 95 will be AED {announced['s95']:.2f} "
                    f"({word}{'' if dir_ == 'stable' else f' {fils} fils'}) from 1 {month_label(nm)}.")
            data["next"] = {"dir": dir_, "note": note}
            data["updated"] = now.strftime("%Y-%m-%d")

    # 3) sem anuncio: previsao pela tendencia do Brent
    if not announced and data["m"] == tm:
        fc = brent_forecast(now)
        if fc and fc != data.get("next"):
            data["next"] = fc

    after = json.dumps(data, sort_keys=True)
    if after != before:
        DATA.write_text(json.dumps(data, indent=2) + "\n")
        print("petrol.json atualizado.")
    else:
        print("Sem alteracoes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
