"""Display the quote's own timestamp, not the report generation time."""
from datetime import datetime
from zoneinfo import ZoneInfo


def odds_label(tip):
    quote = tip.get('odds') or {}
    value = quote.get('rapport')
    if value is None:
        return 'cote PMU SG indisponible'
    kind = 'référence' if quote.get('typeRapport') == 'REFERENCE' else 'direct'
    try:
        stamp = datetime.fromtimestamp(float(quote['dateRapport']) / 1000, ZoneInfo('Europe/Paris'))
        time_label = stamp.strftime('%d/%m %Hh%M')
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        time_label = 'heure non fournie'
    return f'cote PMU SG {value} · {kind} {time_label}'
