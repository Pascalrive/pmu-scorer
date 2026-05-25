#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generer_dashboard.py
--------------------
Lit tous les audits de resultats/audit_*.csv, calcule le bilan de la SELECTION
filtree (la strategie qu'on parie), et genere un tableau de bord HTML autonome
(resultats/tableau_bord_roi.html).

Deux usages :
  1) En ligne de commande :   python3 generer_dashboard.py
  2) Importe depuis pmu_results.py :  from generer_dashboard import generer_dashboard
                                      generer_dashboard()
Le HTML est autonome (donnees injectees en dur) : il suffit de l'ouvrir.
"""
import csv, glob, os, json
from datetime import datetime

OUTPUT_DIR = "resultats"

# ── Validation des bases ────────────────────────────────
# Le systeme "sain" (R/K vivant + rapports repares) demarre le 26/05/2026.
# On ne compte que les paris a partir de cette date pour valider les bases.
DATE_DEMARRAGE = "20260526"      # AAAAMMJJ
OBJECTIF_PARIS = 200             # nombre de paris a accumuler
DATE_REPERE = "13/07/2026"       # horizon calendaire indicatif
ROI_CIBLE = 30.0                 # ROI minimum a tenir pour valider

def _clean(s): return (s or "").replace("\ufeff", "").strip()
def _f(s, d=0.0):
    try: return float(_clean(s))
    except Exception: return d


def calculer_bilan(output_dir=OUTPUT_DIR):
    """Parcourt les audits et renvoie le dict de donnees de la selection."""
    jours = []
    for f in sorted(glob.glob(os.path.join(output_dir, "audit_*.csv"))):
        d = os.path.basename(f).replace("audit_", "").replace(".csv", "")
        if len(d) != 8:
            continue
        date_aff = f"{d[6:8]}/{d[4:6]}"
        with open(f, encoding="utf-8") as fh:
            rows = [{_clean(k): _clean(v) for k, v in r.items()} for r in csv.DictReader(fh)]
        rows = [r for r in rows if r.get("date")]
        if not rows:
            continue
        v7 = "v2n_decision" in rows[0]

        mise = gain = 0.0
        nb_paris = 0
        if v7:
            # Strategie pariee = V2N (le filtre valide en v7)
            for r in rows:
                dec = r.get("v2n_decision", "")
                if dec and dec not in ("NO BET", "DONNEES INSUFFISANTES"):
                    mise += 5.0
                    gain += _f(r.get("v2n_gain"))
                    nb_paris += 1
        else:
            # Ancien format : on rejoue le filtre cote 2-8 / ecart>=2 / partants<=12
            for r in rows:
                cote = _f(r.get("n1_cote"))
                ecart = _f(r.get("ecart_n1_n2"))
                part = int(_f(r.get("nb_partants")))
                if 2.0 <= cote <= 8.0 and ecart >= 2.0 and part <= 12:
                    mise += 5.0
                    gain += _f(r.get("p1_gain"))
                    nb_paris += 1

        jours.append({
            "date": date_aff, "ymd": d, "nb_paris": nb_paris,
            "mise": round(mise, 1), "gain": round(gain, 1),
            "profit": round(gain - mise, 1),
        })

    # Cumuls
    cum_p = cum_m = 0.0
    for j in jours:
        cum_p += j["profit"]; cum_m += j["mise"]
        j["cum_profit"] = round(cum_p, 1)
        j["cum_roi"] = round(cum_p / cum_m * 100, 1) if cum_m else 0.0

    tot_mise = round(sum(j["mise"] for j in jours), 1)
    tot_gain = round(sum(j["gain"] for j in jours), 1)
    tot_paris = sum(j["nb_paris"] for j in jours)
    tot_profit = round(tot_gain - tot_mise, 1)

    # ── Validation : on ne compte que les jours >= DATE_DEMARRAGE ──
    jours_valid = [j for j in jours if j["ymd"] >= DATE_DEMARRAGE]
    v_paris = sum(j["nb_paris"] for j in jours_valid)
    v_mise = round(sum(j["mise"] for j in jours_valid), 1)
    v_gain = round(sum(j["gain"] for j in jours_valid), 1)
    v_profit = round(v_gain - v_mise, 1)
    v_roi = round(v_profit / v_mise * 100, 1) if v_mise else 0.0
    v_gagnants = sum(1 for j in jours_valid if j["profit"] > 0)
    pct = round(min(100, v_paris / OBJECTIF_PARIS * 100), 1) if OBJECTIF_PARIS else 0
    # Conditions de validation (les 3 doivent etre vraies)
    cond_volume = v_paris >= OBJECTIF_PARIS
    cond_roi = v_roi >= ROI_CIBLE
    cond_regularite = (v_gagnants > len(jours_valid) / 2) if jours_valid else False
    valide = cond_volume and cond_roi and cond_regularite

    return {
        "jours": jours,
        "tot_paris": tot_paris,
        "tot_mise": tot_mise,
        "tot_gain": tot_gain,
        "tot_profit": tot_profit,
        "tot_roi": round(tot_profit / tot_mise * 100, 1) if tot_mise else 0.0,
        "jours_gagnants": sum(1 for j in jours if j["profit"] > 0),
        "nb_jours": len(jours),
        "genere_le": datetime.now().strftime("%d/%m/%Y %Hh%M"),
        "periode": (jours[0]["date"] + " au " + jours[-1]["date"]) if jours else "",
        # bloc validation
        "objectif_paris": OBJECTIF_PARIS,
        "date_repere": DATE_REPERE,
        "roi_cible": ROI_CIBLE,
        "v_paris": v_paris,
        "v_mise": v_mise,
        "v_gain": v_gain,
        "v_profit": v_profit,
        "v_roi": v_roi,
        "v_jours": len(jours_valid),
        "v_gagnants": v_gagnants,
        "v_pct": pct,
        "v_restants": max(0, OBJECTIF_PARIS - v_paris),
        "cond_volume": cond_volume,
        "cond_roi": cond_roi,
        "cond_regularite": cond_regularite,
        "valide": valide,
    }


def generer_dashboard(output_dir=OUTPUT_DIR, chemin_sortie=None):
    """Calcule le bilan et ecrit le HTML autonome. Renvoie le chemin du fichier."""
    data = calculer_bilan(output_dir)
    if chemin_sortie is None:
        chemin_sortie = os.path.join(output_dir, "tableau_bord_roi.html")
    html = _construire_html(data)
    with open(chemin_sortie, "w", encoding="utf-8") as f:
        f.write(html)
    return chemin_sortie


def _construire_html(data):
    data_json = json.dumps(data, ensure_ascii=False)
    return _TEMPLATE.replace("/*__DATA__*/", data_json)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PMU Scorer — Tableau de bord ROI (Sélection)</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root{
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2129;
    --line:#2a3038; --txt:#e6edf3; --dim:#8b949e;
    --green:#3fb950; --red:#f85149; --gold:#d9a441;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--txt);font-family:'IBM Plex Mono',monospace;
    line-height:1.5;padding:28px 18px;
    background-image:radial-gradient(circle at 15% 0%,rgba(63,185,80,.06),transparent 40%),
                     radial-gradient(circle at 85% 10%,rgba(217,164,65,.05),transparent 35%);}
  .wrap{max-width:1000px;margin:0 auto}
  header{margin-bottom:24px;border-bottom:1px solid var(--line);padding-bottom:18px}
  .kicker{font-size:11px;letter-spacing:3px;text-transform:uppercase;color:var(--gold)}
  h1{font-family:'Fraunces',serif;font-weight:600;font-size:36px;line-height:1.05;margin:6px 0 4px;letter-spacing:-.5px}
  .sub{color:var(--dim);font-size:13px}
  .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;position:relative;overflow:hidden}
  .card::after{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:var(--green)}
  .card.gold::after{background:var(--gold)} .card.neutral::after{background:var(--dim)}
  .card .lab{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dim)}
  .card .val{font-family:'Fraunces',serif;font-size:30px;font-weight:600;margin-top:6px;letter-spacing:-.5px}
  .card .note{font-size:11px;color:var(--dim);margin-top:3px}
  .pos{color:var(--green)} .neg{color:var(--red)}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px;margin-bottom:18px}
  .panel h2{font-family:'Fraunces',serif;font-size:19px;font-weight:600;margin-bottom:2px}
  .panel .ptip{font-size:12px;color:var(--dim);margin-bottom:16px}
  .chart-box{position:relative;height:330px}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th,td{text-align:right;padding:9px 10px;border-bottom:1px solid var(--line)}
  th{color:var(--dim);font-weight:500;font-size:10.5px;letter-spacing:1px;text-transform:uppercase;position:sticky;top:0;background:var(--panel)}
  td:first-child,th:first-child{text-align:left}
  tbody tr:hover{background:var(--panel2)}
  tfoot td{font-weight:600;border-top:2px solid var(--line);border-bottom:none;color:var(--txt)}
  .tablescroll{max-height:430px;overflow-y:auto;border-radius:8px}
  .legend{display:flex;gap:18px;flex-wrap:wrap;margin-top:14px;font-size:12px}
  .legend span{display:inline-flex;align-items:center;gap:7px;color:var(--dim)}
  .dot{width:11px;height:3px;border-radius:2px;display:inline-block}
  .disc{background:rgba(217,164,65,.1);border:1px solid rgba(217,164,65,.3);border-radius:10px;padding:13px 15px;font-size:12px;color:#f0d9a8;margin-bottom:18px}
  .disc b{color:#ffe9c2}
  .jauge{position:relative;height:30px;background:var(--panel2);border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:6px 0 16px}
  .jauge-fill{height:100%;background:linear-gradient(90deg,#3fb950,#2ea043);border-radius:7px 0 0 7px;transition:width .6s;min-width:2px}
  .jauge-txt{position:absolute;top:0;left:0;right:0;line-height:30px;text-align:center;font-size:12px;font-weight:600;color:var(--txt);text-shadow:0 1px 2px rgba(0,0,0,.6)}
  .conds{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
  .cond{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:12px}
  .cond .ico{font-size:14px;margin-right:6px}
  .cond.ok{border-color:rgba(63,185,80,.4)} .cond.ko{border-color:rgba(248,81,73,.3)}
  .cond .clab{color:var(--dim);font-size:10.5px;letter-spacing:.5px;text-transform:uppercase}
  .cond .cval{margin-top:3px;font-size:13px}
  @media(max-width:720px){.conds{grid-template-columns:1fr}}
  footer{color:var(--dim);font-size:11px;text-align:center;margin-top:24px;line-height:1.7}
  @media(max-width:720px){.grid{grid-template-columns:repeat(2,1fr)}h1{font-size:28px}.chart-box{height:260px}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="kicker">PMU Scorer · Bilan de la sélection</div>
    <h1>Notre sélection — retour sur investissement</h1>
    <div class="sub" id="sub"></div>
  </header>

  <div class="disc" id="disc"></div>

  <div class="panel" id="validBox" style="border-color:rgba(217,164,65,.4)">
    <h2>Validation des bases — objectif <span id="vObj"></span> paris</h2>
    <div class="ptip" id="vTip"></div>
    <div class="jauge"><div class="jauge-fill" id="vFill"></div><span class="jauge-txt" id="vTxt"></span></div>
    <div class="conds" id="vConds"></div>
  </div>

  <div class="grid" id="cards"></div>

  <div class="panel">
    <h2>ROI cumulé jour après jour</h2>
    <div class="ptip">La stabilité recherchée : se maintenir au-dessus de la ligne objectif (+30 %)</div>
    <div class="chart-box"><canvas id="roiChart"></canvas></div>
    <div class="legend">
      <span><i class="dot" style="background:#3fb950"></i> Sélection — ROI cumulé</span>
      <span><i class="dot" style="background:#d9a441"></i> Objectif +30 %</span>
    </div>
  </div>

  <div class="panel">
    <h2>Profit cumulé (€)</h2>
    <div class="ptip">Évolution de la caisse en pariant uniquement la sélection (5 € / pari)</div>
    <div class="chart-box"><canvas id="profitChart"></canvas></div>
  </div>

  <div class="panel">
    <h2>Détail jour par jour</h2>
    <div class="ptip">Nombre de paris, somme misée, somme gagnée et profit — chaque jour</div>
    <div class="tablescroll">
      <table id="tbl">
        <thead><tr>
          <th>Date</th><th>Paris</th><th>Misé</th><th>Gagné</th><th>Profit</th><th>ROI cumulé</th>
        </tr></thead>
        <tbody></tbody>
        <tfoot></tfoot>
      </table>
    </div>
  </div>

  <footer id="foot"></footer>
</div>

<script>
const D = /*__DATA__*/;
const J = D.jours;
const f = (n,p=true)=> (p&&n>0?'+':'')+n.toFixed(1);

document.getElementById('sub').textContent =
  `${D.nb_jours} jours de données réelles · ${D.periode}/2026 · mise 5 € / pari · ${D.tot_paris} paris au total`;

document.getElementById('disc').innerHTML =
  `<b>Résultats simulés (mode shadow) :</b> reconstitués depuis les gains enregistrés dans les audits — aucun argent réel misé. `+
  `Base désormais solide : <b>${D.tot_paris} paris</b> cumulés (seuil de 40 franchi), `+
  `<b>${D.jours_gagnants}/${D.nb_jours} jours gagnants</b>.`;

// ---- Jauge de validation ----
document.getElementById('vObj').textContent = D.objectif_paris;
document.getElementById('vFill').style.width = D.v_pct + '%';
document.getElementById('vTxt').textContent = `${D.v_paris} / ${D.objectif_paris} paris (${D.v_pct.toFixed(0)} %)`;
if (D.v_paris === 0) {
  document.getElementById('vTip').innerHTML =
    `Le système sain (R/K vivant + rapports réparés) démarre le 26/05. `+
    `Comptage des paris à partir de cette date. Horizon repère : <b>${D.date_repere}</b>. `+
    `Il reste <b>${D.v_restants} paris</b> à accumuler.`;
} else {
  document.getElementById('vTip').innerHTML =
    `Depuis le démarrage du système sain · ${D.v_jours} jours · `+
    `il reste <b>${D.v_restants} paris</b> avant validation · horizon repère <b>${D.date_repere}</b>.`;
}
const mk = (ok,lab,val)=>`<div class="cond ${ok?'ok':'ko'}"><span class="ico">${ok?'✅':'⏳'}</span><span class="clab">${lab}</span><div class="cval">${val}</div></div>`;
document.getElementById('vConds').innerHTML =
  mk(D.cond_volume, `Volume ≥ ${D.objectif_paris}`, `${D.v_paris} paris`) +
  mk(D.cond_roi, `ROI ≥ ${D.roi_cible} %`, `${D.v_roi>0?'+':''}${D.v_roi.toFixed(1)} %`) +
  mk(D.cond_regularite, `Majorité de jours +`, `${D.v_gagnants}/${D.v_jours} jours`);
if (D.valide) {
  document.getElementById('validBox').style.borderColor = 'rgba(63,185,80,.5)';
}

// ---- Cards globales ----
const cards = [
  {lab:"Total parié", val:D.tot_mise.toFixed(0)+" €", cls:"neutral", note:`${D.tot_paris} paris · ${D.nb_jours} jours`, vcls:""},
  {lab:"Total gagné", val:D.tot_gain.toFixed(1)+" €", cls:"", note:"retours cumulés", vcls:"pos"},
  {lab:"Profit net", val:f(D.tot_profit)+" €", cls:"", note:`${D.jours_gagnants}/${D.nb_jours} jours gagnants`, vcls:(D.tot_profit>=0?"pos":"neg")},
  {lab:"ROI global", val:f(D.tot_roi)+" %", cls:"gold", note:"objectif +30/40 %", vcls:(D.tot_roi>=0?"pos":"neg")},
];
document.getElementById('cards').innerHTML = cards.map(c=>`
  <div class="card ${c.cls}">
    <div class="lab">${c.lab}</div>
    <div class="val ${c.vcls}">${c.val}</div>
    <div class="note">${c.note}</div>
  </div>`).join('');

// ---- Table ----
document.querySelector('#tbl tbody').innerHTML = J.map(d=>`
  <tr>
    <td>${d.date}</td>
    <td>${d.nb_paris}</td>
    <td>${d.mise.toFixed(0)} €</td>
    <td>${d.gain.toFixed(1)} €</td>
    <td class="${d.profit>=0?'pos':'neg'}">${f(d.profit)} €</td>
    <td class="${d.cum_roi>=0?'pos':'neg'}">${f(d.cum_roi)} %</td>
  </tr>`).join('');
document.querySelector('#tbl tfoot').innerHTML = `
  <tr>
    <td>TOTAL</td>
    <td>${D.tot_paris}</td>
    <td>${D.tot_mise.toFixed(0)} €</td>
    <td>${D.tot_gain.toFixed(1)} €</td>
    <td class="${D.tot_profit>=0?'pos':'neg'}">${f(D.tot_profit)} €</td>
    <td class="${D.tot_roi>=0?'pos':'neg'}">${f(D.tot_roi)} %</td>
  </tr>`;

// ---- Charts ----
const labels = J.map(d=>d.date);
Chart.defaults.color = '#8b949e';
Chart.defaults.font.family = "'IBM Plex Mono', monospace";
Chart.defaults.font.size = 11;
const gridc = 'rgba(138,148,158,.12)';

new Chart(document.getElementById('roiChart'),{
  type:'line',
  data:{labels,datasets:[
    {label:'Sélection',data:J.map(d=>d.cum_roi),borderColor:'#3fb950',
     backgroundColor:'rgba(63,185,80,.12)',fill:true,tension:.3,borderWidth:2.5,pointRadius:3,pointBackgroundColor:'#3fb950'},
    {label:'Objectif',data:J.map(()=>30),borderColor:'#d9a441',borderDash:[6,5],
     borderWidth:1.5,pointRadius:0,fill:false}
  ]},
  options:{responsive:true,maintainAspectRatio:false,
    plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` ${c.dataset.label}: ${f(c.parsed.y)} %`}}},
    scales:{y:{grid:{color:gridc},ticks:{callback:v=>v+' %'}},x:{grid:{color:gridc}}}}
});

new Chart(document.getElementById('profitChart'),{
  type:'line',
  data:{labels,datasets:[
    {label:'Profit cumulé',data:J.map(d=>d.cum_profit),borderColor:'#3fb950',
     backgroundColor:'rgba(63,185,80,.1)',fill:true,tension:.3,borderWidth:2.5,pointRadius:3,pointBackgroundColor:'#3fb950'}
  ]},
  options:{responsive:true,maintainAspectRatio:false,
    plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` ${f(c.parsed.y)} €`}}},
    scales:{y:{grid:{color:gridc},ticks:{callback:v=>v+' €'}},x:{grid:{color:gridc}}}}
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    chemin = generer_dashboard()
    bilan = calculer_bilan()
    print(f"Dashboard genere : {chemin}")
    print(f"  {bilan['tot_paris']} paris | mise {bilan['tot_mise']:.0f}e | "
          f"profit {bilan['tot_profit']:+.1f}e | ROI {bilan['tot_roi']:+.1f}% | "
          f"{bilan['jours_gagnants']}/{bilan['nb_jours']} jours gagnants")
