"""Journal des messages Telegram et bilan des seules selections envoyees.
Rapports definitifs PMU INTERNET, en centimes par euro, par combinaison.
Aucune estimation de rapport. La mise de 5 EUR est une simulation, pas un pari execute.
"""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Paris')
JOURNAL = Path('resultats/journal')
BASE = 'https://online.turfinfo.api.pmu.fr/rest/client/61'
LABELS = {'SIMPLE_PLACE': 'Simple place', 'COUPLE_PLACE': 'Couple place',
          'COUPLE_GAGNANT': 'Couple gagnant', 'COUPLE_ORDRE': 'Couple ordre'}
LOG = logging.getLogger(__name__)


def normaliser_identite(value):
    return re.sub(r'[^A-Z0-9]', '', unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().upper())


def identite_message(text):
    match = re.search(r'^DATE : \d{4}-\d{2}-\d{2}\s*\n([^\n]+)\n([^\n]+)', text, re.M)
    return {'hippodrome': match[1].strip(), 'libelle': match[2].strip()} if match else {}


def erreur_identite(identite, officiel, nr, nc):
    """Identite officielle obligatoire ; ne jamais corriger un journal a posteriori."""
    if not isinstance(officiel, dict) or not officiel.get('numReunion') or not officiel.get('numOrdre'):
        return 'Identite officielle indisponible'
    if (str(officiel['numReunion']), str(officiel['numOrdre'])) != (str(nr), str(nc)):
        return 'Numero de course incompatible avec la source officielle'
    if not identite.get('hippodrome') or not identite.get('libelle'):
        return 'Identite absente du message ou du CSV initial'
    def hip(value):
        return re.sub(r'^HIPPODROME(?:DE|D)?', '', normaliser_identite(value))
    hippodrome = officiel.get('hippodrome') or {}
    noms = {hip(hippodrome.get(k)) for k in ('libelleLong', 'libelleCourt')}
    if hip(identite['hippodrome']) not in noms:
        return 'Hippodrome different de la course officielle'
    if normaliser_identite(identite['libelle']) != normaliser_identite(officiel.get('libelle')):
        return 'Nom de course different de la course officielle'
    return ''


def erreur_chevaux(choix, participants):
    runners = {str(p.get('numPmu')): p for p in participants}
    for ch in choix:
        runner = runners.get(str(ch['num']))
        if not runner or not runner.get('nom'):
            return f"Identite du cheval N{ch['num']} indisponible"
        if normaliser_identite(ch['nom']) != normaliser_identite(runner['nom']):
            return f"Numero et nom du cheval N{ch['num']} incompatibles"
    return ''


def formater_selection(top, nb_partants, actualisation=False, marches=None, day=None):
    """Présentation seule : aucun changement des chevaux ni des mises."""
    lines = ['CHEVAUX RETENUS']
    for i, ch in enumerate(top[:2]):
        role = '1er choix' if i == 0 else '2e choix'
        lines.append(f"{role} : N{ch.get('num_partant', '?')}. {ch.get('nom_cheval', '?')}")
        cote = ch.get('cote_actuel' if actualisation else 'cote_jour', 0) or 0
        detail = f"Cote {cote:.1f}" if cote > 0 else 'Cote indisponible'
        initiale = ch.get('cote_jour', 0) or 0
        if actualisation and initiale > 0 and cote > 0:
            variation = (cote / initiale - 1) * 100
            detail += f" (initiale {initiale:.1f} ; {variation:+.0f} %)"
        lines.append(detail)
        lines.append('')
    lines.append('PARIS CONSEILLES')
    lines.extend(paris_affiches(top[:2], nb_partants, marches, day=day))
    return lines


def archiver_observation(course, phase, partants, *, calcul=None, debut=None, source_csv=None):
    now = datetime.now(TZ)
    path = Path('resultats/observations') / f'{now:%Y%m%d}' / f'{uuid4().hex}.json'
    _write(path, {'schema': 1, 'phase': phase, 'debut_collecte': debut or now.isoformat(),
                  'fin_collecte': now.isoformat(), 'course': course, 'partants': partants,
                  'calcul': calcul, 'source_csv': source_csv,
                  'revision': os.environ.get('GITHUB_SHA', 'local')})
    return path


def paris_affiches(top, nb_partants, marches=None, day=None):
    if day and str(day).replace('-', '') >= '20261102':
        original = paris_affiches(top, nb_partants, marches)
        retained = [line for line in original if line.startswith('COUPLE ORDRE :')]
        return retained or ['AUCUN PARI CONSEILLE : seul le couple ordre est actif depuis le 02/11.']
    return _paris_affiches_legacy(top, nb_partants, marches)


def _paris_affiches_legacy(top, nb_partants, marches=None):
    """Une seule source pour les lignes de paris, sans modifier le classement."""
    if not top:
        return ['AUCUN PARI CONSEILLE : selection indisponible.']
    a = top[0]
    n1 = str(a.get('num_partant') or '').strip()
    if not n1.isdigit():
        return ['AUCUN PARI CONSEILLE : numero manquant.']
    if marches is not None and 'SIMPLE_PLACE' not in marches:
        return ['AUCUN PARI CONSEILLE : simple place PMU Internet non disponible.']
    lines = [f"PARI : Simple Place sur N{n1}"]
    if len(top) > 1:
        b = top[1]
        n2 = str(b.get('num_partant') or '').strip()
        odds = b.get('cote_actuel', b.get('cote_jour', 0)) or 0
        if n2.isdigit() and n1 != n2 and 0 < odds < 12 and nb_partants >= 4:
            if marches is None:
                kind = 'GAGNANT' if nb_partants <= 7 else 'PLACE'  # Lecture des anciens formats.
            else:
                kind = next((k for k in ('PLACE', 'ORDRE', 'GAGNANT') if 'COUPLE_' + k in marches), None)
            if kind:
                suffix = ' (dans cet ordre)' if kind == 'ORDRE' else ''
                lines.append(f"COUPLE {kind} : N{n1} + N{n2}{suffix}")
    return lines


def analyser_message(text, now):
    """Parse uniquement le format explicite emis par nos deux programmes."""
    match = re.search(r'COURSE\s*:?\s*R(\d+)\s*C(\d+)', text)
    if not match:
        return None
    clock = re.search(r'(?:DEPART|HEURE\s*:)\s*(\d{2})h(\d{2})', text)
    if not clock:
        raise ValueError('Course sans heure de depart : journal incomplet')
    depart = now.replace(hour=int(clock[1]), minute=int(clock[2]), second=0, microsecond=0)
    date = re.search(r'DATE : (\d{4}-\d{2}-\d{2})', text)
    if date:
        day = datetime.strptime(date[1], '%Y-%m-%d')
        depart = depart.replace(year=day.year, month=day.month, day=day.day)
    choices = []
    for role, num, name in re.findall(r'(PRONOSTIC PRINCIPAL|DEUXIEME CHOIX|1er choix|2e choix)\s*:\s*(?:🔴\s*)?N(\d+)\.\s*([^\n]+)', text):
        if len(choices) == 2:
            break
        choices.append({'num': str(int(num)), 'nom': name.split(' (cote')[0].strip()})
    bets = []
    simple = re.search(r'PARI\s*:\s*Simple Place sur N(\d+)', text)
    if simple:
        bets.append({'type': 'SIMPLE_PLACE', 'numeros': [str(int(simple[1]))], 'mise': '5.00'})
    couple = re.search(r'COUPLE (PLACE|GAGNANT|ORDRE)[^\n]*?:\s*N(\d+)[^\n]*?\+\s*N(\d+)', text)
    if couple:
        bets.append({'type': 'COUPLE_' + couple[1], 'numeros': [str(int(couple[2])), str(int(couple[3]))], 'mise': '5.00'})
    if choices and not bets and not (depart.date().isoformat()>='2026-11-02' and 'AUCUN PARI CONSEILLE' in text):
        raise ValueError('Choix sans pari explicite : ne pas inventer la mise')
    selected = [c['num'] for c in choices]
    for bet in bets:
        if not selected or bet['numeros'] != selected[:len(bet['numeros'])]:
            raise ValueError('Incoherence entre chevaux affiches et paris')
    return {'date': depart.strftime('%Y%m%d'), 'course': f'R{match[1]}C{match[2]}',
            'depart': depart.isoformat(), 'source': 'H15' if 'ACTUALISATION' in text else 'MATIN',
            'choix': choices, 'paris': bets, 'identite': identite_message(text)}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def envoyer_trace(text, token, chat_id, *, post=None, journal=None, now=None, experience=None):
    """Un recu par course ; les envois incomplets restent explicitement incertains."""
    if not token or not chat_id:
        return False
    if post is None:
        import requests
        post = requests.post
    fixed_now = now
    now = now or datetime.now(TZ)
    journal = Path(journal) if journal is not None else JOURNAL
    # Separer les courses pour pouvoir attester chaque selection independamment.
    blocks = re.split(r'(?=^[^\w\n]*COURSE\s*:?\s*R\d+\s*C\d+)', text, flags=re.M)
    source_h15 = 'ACTUALISATION DE L\'ALGORITHME' in text
    has_courses = bool(re.search(r'COURSE\s*:?\s*R\d+\s*C\d+', text))
    success = True
    for block in blocks:
        if not block.strip():
            continue
        event = analyser_message(('ACTUALISATION\n' if source_h15 else '') + block, now)
        if has_courses and event is None:
            continue  # Une fiche par course, sans en-tete isole ni recapitulatif perime.
        if event and event['date'] >= '20261102':
            if any(b['type'] != 'COUPLE_ORDRE' for b in event['paris']):
                raise ValueError('Formule suspendue depuis le 02/11 : envoi bloqué')
            experience = None
        record = {'schema': 1, 'id': uuid4().hex, 'sent_at': now.isoformat(),
                  'revision': os.environ.get('GITHUB_SHA', 'local'), 'event': event,
                  'text': block, 'sha256': hashlib.sha256(block.encode()).hexdigest(),
                  'delivery': 'PENDING', 'receipts': []}
        if event and experience is not None:
            record['experience'] = experience
        path = journal / f"{now:%Y%m%d}-{record['id']}.json"
        if event:
            _write(path, record)  # Echec disque => ne pas envoyer sans trace.
            if (fixed_now or datetime.now(TZ)) >= datetime.fromisoformat(event['depart']):
                record['delivery'] = 'BLOCKED_AFTER_START'
                _write(path, record)
                LOG.warning('Envoi bloque apres depart : %s', event['course'])
                success = False
                continue
        try:
            for pos in range(0, len(block), 3500):
                response = post(f'https://api.telegram.org/bot{token}/sendMessage',
                                json={'chat_id': chat_id, 'text': block[pos:pos+3500]}, timeout=20)
                body = response.json()
                if response.status_code != 200 or body.get('ok') is not True:
                    raise ValueError('Telegram refuse le message')
                result = body['result']
                record['receipts'].append({'message_id': result['message_id'], 'date': result['date']})
                if event:
                    _write(path, record)
            record['delivery'] = 'SENT'
            # Date du dernier morceau confirmee par Telegram, pas l'horloge du runner.
            record['sent_at'] = datetime.fromtimestamp(record['receipts'][-1]['date'], TZ).isoformat()
        except Exception as exc:
            record['delivery'] = 'UNCERTAIN'
            LOG.warning('Envoi Telegram non confirme (%s)', type(exc).__name__)
            success = False
        if event:
            _write(path, record)
    return success


def dernieres_selections(records, day):
    chosen = {}
    for row in records:
        e = row.get('event')
        if not e or e['date'] != day:
            continue
        sent = datetime.fromisoformat(row['sent_at'])
        if sent >= datetime.fromisoformat(e['depart']):
            continue  # Pas de pronostic retrospectif.
        previous = chosen.get(e['course'])
        if previous is None or sent > datetime.fromisoformat(previous['sent_at']):
            chosen[e['course']] = row
        elif sent == datetime.fromisoformat(previous['sent_at']) and row['sha256'] != previous['sha256']:
            # Deux versions differentes dans la meme seconde : ne pas choisir arbitrairement.
            chosen[e['course']] = {**row, 'delivery': 'UNCERTAIN'}
    return chosen


def tables_rapports(payload):
    """Ne reconnait que le contrat observe de rapports-definitifs INTERNET."""
    tables = {}
    if not isinstance(payload, list):
        return tables
    for item in payload:
        kind = item.get('typePari', '')
        if not kind.startswith('E_'):
            continue
        kind = kind[2:]
        if kind not in LABELS:
            continue
        table = {'rembourse': item.get('rembourse') is True, 'valeurs': {}}
        for r in item.get('rapports', []):
            combination = str(r.get('combinaison', ''))
            if not re.fullmatch(r'(?:\d+|NP)(?:-(?:\d+|NP))*', combination):
                continue
            try:
                amount = Decimal(str(r['dividendePourUnEuro'])) / Decimal(100)
            except (KeyError, InvalidOperation):
                continue
            if not amount.is_finite() or amount <= 0:
                continue
            key = tuple(combination.split('-')) if kind == 'COUPLE_ORDRE' else tuple(sorted(combination.split('-')))
            if key in table['valeurs'] and table['valeurs'][key] != amount:
                raise ValueError('Rapports contradictoires pour une combinaison')
            table['valeurs'][key] = amount
        if table['rembourse'] or table['valeurs']:
            if kind in tables and tables[kind] != table:
                raise ValueError('Plusieurs tables de rapports incompatibles')
            tables[kind] = table
    return tables


def regler_pari(bet, participants, tables, *, definitif=False):
    kind, nums = bet['type'], bet['numeros']
    stake = Decimal(bet['mise'])
    def result(status, returned=None, reason=''):
        return {**bet, 'statut': status, 'retour': None if returned is None else str(returned.quantize(Decimal('.01'))), 'raison': reason}
    table = tables.get(kind)
    if not table:
        return result('EN_ATTENTE', reason='Rapports definitifs absents')
    if table['rembourse']:
        return result('REMBOURSE', stake, 'Pari rembourse par PMU')
    runners = {str(p.get('numPmu')): p for p in participants}
    if any(n not in runners for n in nums):
        return result('EN_ATTENTE', reason='Participant non identifie')
    np = {n for n in nums if runners[n].get('statut') == 'NON_PARTANT' or runners[n].get('incident') == 'NON_PARTANT'}
    if np and kind == 'SIMPLE_PLACE':
        return result('REMBOURSE', stake, 'Non-partant officiel')
    key = tuple('NP' if n in np else n for n in nums)
    if kind != 'COUPLE_ORDRE':
        key = tuple(sorted(key))
    dividend = table['valeurs'].get(key)
    if dividend is not None:
        return result('REGLE_NP' if np else 'GAGNE', stake * dividend, f'Rapport officiel {dividend} EUR pour 1 EUR')
    if np:
        return result('EN_ATTENTE', reason='Couple avec non-partant : rapport specifique requis')
    if definitif and any(not (runners[n].get('statut') == 'PARTANT' or runners[n].get('ordreArrivee')
                             or runners[n].get('incident') in {'DISQUALIFIE', 'ARRETE', 'TOMBE', 'DISTANCE'}) for n in nums):
        return result('EN_ATTENTE', reason='Statut du participant non confirme')
    # Ne pas convertir un resultat de participant inconnu en perte.
    if not definitif and not all(p.get('ordreArrivee', 0) or p.get('incident') in {'DISQUALIFIE', 'ARRETE', 'TOMBE', 'DISTANCE'} for p in (runners[n] for n in nums)):
        return result('EN_ATTENTE', reason='Classement ou incident non confirme')
    return result('PERDU', Decimal(0), 'Combinaison absente des rapports definitifs')


def regler_experience(record, participants, tables):
    if (record.get('event') or {}).get('date', '') >= '20261102':return None
    if record.get('delivery') != 'SENT':
        return None
    exp = record.get('experience') or {}
    reference, variante = exp.get('reference'), exp.get('variante_outsider')
    if not reference or not variante:
        return None
    event = record['event']
    if reference.get('choix') != event['choix'] or reference.get('paris') != event['paris']:
        return None  # Comparaison exclusivement avec le conseil confirme par Telegram.
    if len(variante.get('paris', [])) != len(reference['paris']):
        return None
    if sum(Decimal(b['mise']) for b in variante['paris']) != sum(Decimal(b['mise']) for b in reference['paris']):
        return None
    if erreur_chevaux(variante.get('choix', []), participants):
        return None
    result = {'version': exp.get('version'), 'reference': reference, 'variante_outsider': variante}
    complete = True
    for key in ('reference', 'variante_outsider'):
        bets = [regler_pari(b, participants, tables, definitif=bool(tables)) for b in exp[key]['paris']]
        done = all(b['retour'] is not None for b in bets)
        complete = complete and done
        result[key] = {**exp[key], 'reglements': bets,
                       'mise': str(sum(Decimal(b['mise']) for b in bets)),
                       'retour': str(sum(Decimal(b['retour']) for b in bets)) if done else None}
    result['complet'] = complete
    return result


def bilan(records, day, fetch):
    selections = dernieres_selections(records, day)
    if not selections:
        return (f'ALERTE SUIVI PMU — {day[6:8]}/{day[4:6]}/{day[:4]}\n'
                'Bilan indisponible : aucun pronostic envoye avant depart retrouve.\n'
                f'Journaux charges : {len(records)}.\n'
                'Aucun historique exploitable : verifier la collecte initiale et les envois.\n'
                'Aucun taux de reussite ni resultat financier calculable.\n'
                'Aucun remplacement par les CSV du scoreur.'), []
    lines = [f'BILAN DES PRONOSTICS ENVOYES — {day[6:8]}/{day[4:6]}/{day[:4]}',
             'Derniere version envoyee avant depart, une seule selection par course.',
             'Simulation : 5 EUR par pari explicitement conseille ; aucun pari execute.',
             'Rapports officiels PMU INTERNET uniquement.']
    audit = []
    experiences = []
    won = placed = evaluated = pending_choices = 0
    for key, record in sorted(selections.items()):
        event = record['event']
        lines.append(f"\n{key} — {event['source']} — envoi {datetime.fromisoformat(record['sent_at']).strftime('%Hh%M')}")
        if record['delivery'] != 'SENT':
            lines.append('ENVOI INCERTAIN : exclu du bilan, pas de remplacement par le choix du matin.')
            audit.append({'course': key, 'statut': 'ENVOI_INCERTAIN', 'journal_id': record['id']})
            pending_choices += 1
            continue
        if not event['choix']:
            lines.append('Aucune selection finale conseillee.')
            continue
        nr, nc = re.fullmatch(r'R(\d+)C(\d+)', key).groups()
        api_date = day[6:8] + day[4:6] + day[:4]
        prefix = f'/programme/{api_date}/R{nr}/C{nc}'
        officiel = fetch(prefix)
        raison = erreur_identite(event.get('identite') or identite_message(record.get('text', '')), officiel, nr, nc)
        participants_payload = fetch(prefix + '/participants') if not raison else None
        participants = (participants_payload or {}).get('participants', []) if isinstance(participants_payload, dict) else []
        raison = raison or erreur_chevaux(event['choix'], participants)
        if not raison and officiel.get('heureDepart'):
            if datetime.fromisoformat(record['sent_at']).timestamp() * 1000 >= officiel['heureDepart']:
                raison = 'Envoi apres le depart officiel'
        if raison:
            lines.append('CONTROLE BLOQUANT : ' + raison + '. Course exclue des calculs.')
            audit.append({'course': key, 'statut': 'IDENTITE_NON_VALIDEE', 'raison': raison,
                          'journal_id': record['id'], 'source_url': BASE + prefix})
            pending_choices += 1
            continue
        payload = fetch(prefix + '/rapports-definitifs?specialisation=INTERNET')
        tables = tables_rapports(payload)
        runners = {str(p.get('numPmu')): p for p in participants}
        for i, c in enumerate(event['choix']):
            runner = runners.get(c['num'], {})
            rank = runner.get('ordreArrivee')
            status = 'NON-PARTANT' if runner.get('statut') == 'NON_PARTANT' else (f'{rank}e' if rank else 'EN ATTENTE / NON CLASSE')
            lines.append(f"Choix {i+1} : N{c['num']} {c['nom']} — {status}")
        primary = event['choix'][0]['num']
        # Les rapports definitifs complets permettent aussi de regler un partant
        # non classe sans confondre absence de rang et absence de resultat.
        settlements = []
        marches = {p.get('typePari', '')[2:] for p in officiel.get('paris', []) if p.get('typePari', '').startswith('E_')}
        for b in event['paris']:
            if officiel.get('hasEParis') is False or ('paris' in officiel and b['type'] not in marches):
                settlements.append({**b, 'statut': 'NON_PROPOSE', 'retour': None,
                                    'raison': 'Pari exact non propose par PMU Internet ; mise exclue'})
            else:
                settlements.append(regler_pari(b, participants, tables, definitif=bool(tables)))
        experiment = regler_experience(record, participants, tables)
        if experiment and settlements:
            settlements[0]['comparaison_experimentale'] = experiment
            experiences.append(experiment)
        for settled in settlements:
            audit.append({**settled, 'course': key, 'journal_id': record['id'], 'source': event['source'], 'sent_at': record['sent_at'],
                          'rapport_url': BASE + prefix + '/rapports-definitifs?specialisation=INTERNET'})
            amount = f" ; retour {settled['retour']} EUR" if settled['retour'] is not None else ''
            lines.append(f"{LABELS[settled['type']]} {'+'.join(settled['numeros'])} : {settled['statut']}{amount}")
            if settled['type'] == 'SIMPLE_PLACE':
                if settled['statut'] in {'GAGNE', 'PERDU'}:
                    evaluated += 1
                    placed += settled['statut'] == 'GAGNE'
                    won += runners.get(primary, {}).get('ordreArrivee') == 1
                elif settled['statut'] == 'EN_ATTENTE':
                    pending_choices += 1
    lines += ['', f'Premier choix gagnant : {won}/{evaluated} classes et regles.',
              f'Premier choix place (gagnants inclus) : {placed}/{evaluated} classes et regles.',
              f'Courses en attente, incoherentes ou envoi incertain : {pending_choices}. Non-partants exclus des taux.']
    settled = [r for r in audit if r.get('retour') is not None]
    unresolved = [r for r in audit if r.get('statut') in {'EN_ATTENTE', 'ENVOI_INCERTAIN', 'IDENTITE_NON_VALIDEE'}]
    refunded = sum(r['statut'] == 'REMBOURSE' for r in settled)
    excluded = sum(r.get('statut') == 'NON_PROPOSE' for r in audit)
    invested = sum((Decimal(r['mise']) for r in settled), Decimal(0))
    returns = sum((Decimal(r['retour']) for r in settled), Decimal(0))
    lines += [f'Paris regles : {len(settled)}, dont {refunded} rembourses. Paris/envois en attente : {len(unresolved)}.',
              f'Sous-total regle : mises {invested:.2f} EUR ; retours {returns:.2f} EUR ; solde {returns-invested:+.2f} EUR.']
    if excluded:
        lines.append(f'Paris non proposes exclus des mises : {excluded}. ROI limite aux paris valides.')
    if unresolved or not selections:
        lines.append('BILAN INCOMPLET : aucun ROI global publie.')
    elif invested:
        lines.append(f'ROI simule sur les paris regles : {(returns/invested-1)*100:+.1f} %.')
    matched = [e for e in experiences if e['complet']]
    if matched:
        lines += ['', f'EXPERIENCE OUTSIDER — {len(matched)} course(s) comparee(s), memes mises. Simulation uniquement.']
        for key, label in (('reference', 'Conseils envoyes'), ('variante_outsider', 'Variante outsider non conseillee')):
            stakes = sum(Decimal(e[key]['mise']) for e in matched)
            returned = sum(Decimal(e[key]['retour']) for e in matched)
            lines.append(f'{label} : mises {stakes:.2f} EUR ; retours {returned:.2f} EUR ; ROI {(returned/stakes-1)*100:+.1f} %.')
    if any(not e['complet'] for e in experiences):
        lines.append('Comparaisons outsider en attente de reglement : ' + str(sum(not e['complet'] for e in experiences)))
    if not selections:
        lines.append('Aucun historique d\'envoi avant depart disponible. Aucun remplacement par les CSV du scoreur.')
    lines.append('Les anciennes simulations estimees ne sont pas comparables a ce bilan.')
    return '\n'.join(lines), audit


def couverture_sans_envoi(day, fetch):
    """Aucun pari seulement si le programme complet prouve l'absence de marche."""
    if day < '20261102':
        return {'status': 'HISTORIQUE_MANQUANT'}
    api_date = day[6:8] + day[4:6] + day[:4]
    payload = fetch(f'/programme/{api_date}?specialisation=INTERNET')
    reunions = (payload or {}).get('programme', {}).get('reunions')
    if not isinstance(reunions, list) or not reunions:
        return {'status': 'PROGRAMME_INDISPONIBLE'}
    eligible = []
    for reunion in reunions:
        pays = reunion.get('pays', {})
        code = pays.get('code', '') if isinstance(pays, dict) else str(pays)
        if code not in {'FRA', 'FRANCE'}:
            continue
        courses = reunion.get('courses')
        if not isinstance(courses, list) or not courses:
            return {'status': 'PROGRAMME_INCOMPLET'}
        for course in courses:
            if not isinstance(course.get('paris'), list) or not course['paris']:
                return {'status': 'PROGRAMME_INCOMPLET'}
            # Apres depart, enVente=false ne signifie pas que le marche etait absent.
            if any(p.get('typePari') == 'E_COUPLE_ORDRE' for p in course['paris']):
                eligible.append(f"R{reunion['numOfficiel']}C{course['numOrdre']}")
    return {'status': 'ENVOIS_MANQUANTS' if eligible else 'AUCUNE_COURSE_ELIGIBLE',
            'courses_eligibles': eligible}


def main():
    import requests
    day = os.environ.get('PMU_BILAN_DATE', datetime.now(TZ).strftime('%Y%m%d'))
    if not re.fullmatch(r'\d{8}', day):
        raise ValueError('PMU_BILAN_DATE doit etre au format AAAAMMJJ')
    datetime.strptime(day, '%Y%m%d')
    records = [json.loads(p.read_text(encoding='utf-8')) for p in JOURNAL.glob(f'{day}-*.json')]
    snapshot_dir = Path('resultats/officiels') / day
    def fetch(path):
        try:
            r = requests.get(BASE + path, timeout=25)
            r.raise_for_status()
            data = r.json()
            _write(snapshot_dir / (hashlib.sha256(path.encode()).hexdigest() + '.json'),
                   {'url': BASE + path, 'retrieved_at': datetime.now(TZ).isoformat(), 'payload': data})
            return data
        except requests.RequestException:
            LOG.warning('Donnees PMU indisponibles pour %s', path)
            return None
    message, audit = bilan(records, day, fetch)
    coverage = None
    if not dernieres_selections(records, day):
        coverage = couverture_sans_envoi(day, fetch)
        if coverage['status'] == 'AUCUNE_COURSE_ELIGIBLE':
            message = (f'BILAN SCORER — {day[6:8]}/{day[4:6]}/{day[:4]}\n'
                       'Aucune course francaise avec Couple ordre PMU Internet au programme.\n'
                       'Aucun pari : mises 0 EUR ; retours 0 EUR ; net 0 EUR ; ROI non applicable.\n'
                       'Simulation uniquement ; aucun pari reel.')
        else:
            message += '\nCOUVERTURE : ' + coverage['status']
            if coverage.get('courses_eligibles'):
                message += ' — ' + ', '.join(coverage['courses_eligibles'])
    destination = Path('resultats/bilans')
    _write(destination / f'bilan_{day}.json', {'date': day, 'generated_at': datetime.now(TZ).isoformat(), 'audit': audit, 'message': message, 'coverage': coverage})
    print(message)
    if os.environ.get('PMU_DRY_RUN') != '1':
        if not envoyer_trace(message, os.environ.get('TELEGRAM_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')):
            raise RuntimeError('Bilan non envoye a Telegram')
    if coverage and coverage['status'] != 'AUCUNE_COURSE_ELIGIBLE':
        raise RuntimeError('SUIVI EN ECHEC : aucun historique avant depart ; diagnostic archive')


if __name__ == '__main__':
    main()


