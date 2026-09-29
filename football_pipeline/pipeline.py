"""Extract public JSON, validate matches, upsert SQL rows, export standings."""
import argparse
import csv
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from datetime import date, datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

DEFAULT_URL = 'https://raw.githubusercontent.com/openfootball/football.json/master/2024-25/en.1.json'
LOG = logging.getLogger(__name__)
SCHEMA = '''CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY, competition TEXT NOT NULL, round TEXT NOT NULL,
    match_date TEXT NOT NULL, home_team TEXT NOT NULL, away_team TEXT NOT NULL,
    home_goals INTEGER, away_goals INTEGER,
    CHECK(home_team <> away_team),
    CHECK(home_goals >= 0 AND away_goals >= 0),
    CHECK((home_goals IS NULL) = (away_goals IS NULL))
)'''
STANDINGS = '''WITH performances AS (
 SELECT competition, home_team AS team, home_goals AS gf, away_goals AS ga
 FROM matches WHERE home_goals IS NOT NULL
 UNION ALL
 SELECT competition, away_team AS team, away_goals AS gf, home_goals AS ga
 FROM matches WHERE away_goals IS NOT NULL
)
SELECT team, COUNT(*) AS played,
 SUM(CASE WHEN gf > ga THEN 1 ELSE 0 END) AS won,
 SUM(CASE WHEN gf = ga THEN 1 ELSE 0 END) AS drawn,
 SUM(CASE WHEN gf < ga THEN 1 ELSE 0 END) AS lost,
 SUM(gf) AS goals_for, SUM(ga) AS goals_against, SUM(gf-ga) AS goal_difference,
 SUM(CASE WHEN gf > ga THEN 3 WHEN gf = ga THEN 1 ELSE 0 END) AS points
FROM performances WHERE competition = {placeholder}
GROUP BY team ORDER BY points DESC, goal_difference DESC, goals_for DESC, team'''


def extract(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'football-data-pipeline/1.0'}), timeout=30) as response:
                return response.read()
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            LOG.warning('Download failed; retry %s of 2', attempt + 1)
            time.sleep(2 ** attempt)


def required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonempty string')
    return value.strip()


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError('Expected an object at the root')
    competition = required_text(payload.get('name'), 'name')
    matches = payload.get('matches')
    if not isinstance(matches, list) or not matches:
        raise ValueError('matches must be a nonempty list')
    rows, seen = [], set()
    for index, match in enumerate(matches):
        try:
            if not isinstance(match, dict):
                raise ValueError('match must be an object')
            home = required_text(match.get('team1'), 'team1')
            away = required_text(match.get('team2'), 'team2')
            if home == away:
                raise ValueError('teams must differ')
            round_name = required_text(match.get('round'), 'round')
            match_date = date.fromisoformat(required_text(match.get('date'), 'date')).isoformat()
            score = match.get('score', {})
            if not isinstance(score, dict):
                raise ValueError('score must be an object')
            ft = score.get('ft')
            if ft is None:
                home_goals = away_goals = None
            elif (isinstance(ft, list) and len(ft) == 2
                  and all(type(x) is int and x >= 0 for x in ft)):
                home_goals, away_goals = ft
            else:
                raise ValueError('full-time score must contain two nonnegative integers')
            # Date is deliberately excluded: postponed games must update, not duplicate.
            key = json.dumps([competition, round_name, home, away], ensure_ascii=False)
            match_id = hashlib.sha256(key.encode()).hexdigest()
            if match_id in seen:
                raise ValueError('duplicate fixture identity')
            seen.add(match_id)
            rows.append((match_id, competition, round_name, match_date, home, away, home_goals, away_goals))
        except (ValueError, TypeError) as exc:
            raise ValueError(f'matches[{index}]: {exc}') from exc
    return competition, rows


def connect(database_url, sqlite_path):
    if database_url:
        import psycopg
        return psycopg.connect(database_url, connect_timeout=15), '%s'
    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path), '?'


def load(conn, placeholder, rows, competition):
    values = ','.join([placeholder] * 8)
    statement = f'''INSERT INTO matches VALUES ({values})
      ON CONFLICT(match_id) DO UPDATE SET match_date=excluded.match_date,
      home_goals=excluded.home_goals, away_goals=excluded.away_goals'''
    try:
        cur = conn.cursor()
        cur.execute(SCHEMA)
        cur.executemany(statement, rows)
        cur.execute(STANDINGS.format(placeholder=placeholder), (competition,))
        headers = [col[0] for col in cur.description]
        standings = cur.fetchall()
        cur.execute(f'SELECT COUNT(*) FROM matches WHERE competition={placeholder}', (competition,))
        count = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return headers, standings, count
    except Exception:
        conn.rollback()
        raise


def run(source_url=DEFAULT_URL, input_file=None, output_dir='data', database_url=None, sqlite_path='data/football.db'):
    output = Path(output_dir)
    raw_dir = output / 'raw'
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw = Path(input_file).read_bytes() if input_file else extract(source_url)
    checksum = hashlib.sha256(raw).hexdigest()
    snapshot = raw_dir / f'{checksum}.json'
    snapshot.write_bytes(raw)
    competition, rows = validate(json.loads(raw))
    LOG.info('Validated %s records for %s', len(rows), competition)
    conn, placeholder = connect(database_url, sqlite_path)
    try:
        headers, standings, count = load(conn, placeholder, rows, competition)
    finally:
        conn.close()
    with (output / 'standings.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(standings)
    manifest = {
        'completed_at_utc': datetime.now(timezone.utc).isoformat(),
        'competition': competition, 'source': str(input_file) if input_file else source_url,
        'source_sha256': checksum, 'validated_records': len(rows),
        'completed_matches': sum(r[6] is not None for r in rows),
        'stored_matches': count, 'teams_in_standings': len(standings),
        'database_backend': 'postgresql' if database_url else 'sqlite',
    }
    (output / 'run.json').write_text(json.dumps(manifest, indent=2) + '\n')
    LOG.info('Load complete: %s stored matches; %s teams', count, len(standings))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-url', default=DEFAULT_URL)
    parser.add_argument('--input', dest='input_file', help='Replay a local source snapshot')
    parser.add_argument('--output-dir', default='data')
    parser.add_argument('--sqlite-path', default='data/football.db')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        run(**vars(args), database_url=os.getenv('DATABASE_URL'))
    except Exception as exc:
        # Avoid emitting connection strings or credentials in logs.
        LOG.error('Pipeline failed (%s). No successful run reported.', type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
