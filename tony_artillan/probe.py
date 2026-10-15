"""Diagnostic public d'acces a la source depuis GitHub Actions."""
import json
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup


def main():
    root = Path('tony_artillan/data/probe')
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, url in [('home', 'https://www.paris-turf.com/'),
                      ('programme', 'https://www.paris-turf.com/programme-courses')]:
        row = {'url': url, 'at': datetime.now(timezone.utc).isoformat()}
        try:
            r = requests.get(url, timeout=20)
            soup = BeautifulSoup(r.text, 'html.parser')
            row.update(status=r.status_code, final_url=r.url, title=soup.title.get_text() if soup.title else '',
                       text=soup.get_text(' ', strip=True)[:6000],
                       links=[{'text': a.get_text(' ', strip=True), 'href': a.get('href')}
                              for a in soup.select('a[href]')][:250],
                       scripts=[a.get('src') for a in soup.select('script[src]')])
            (root / (name+'.html')).write_text(r.text)
        except requests.RequestException as e:
            row['error'] = type(e).__name__
        rows.append(row)
    (root / 'access.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(json.dumps([{k:v for k,v in r.items() if k not in ('links','scripts')} for r in rows], ensure_ascii=False))


if __name__ == '__main__':
    main()
