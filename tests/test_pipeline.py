import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from football_pipeline.pipeline import validate, load, run, connect

FIXTURE = {'name': 'Test League 2024/25', 'matches': [
    {'round': 'Round 1', 'date': '2024-08-01', 'team1': 'A', 'team2': 'B', 'score': {'ft': [2, 1]}},
    {'round': 'Round 2', 'date': '2024-08-08', 'team1': 'B', 'team2': 'A', 'score': {'ft': [0, 0]}},
]}


class PipelineTests(unittest.TestCase):
    def test_rerun_and_correction(self):
        conn = sqlite3.connect(':memory:')
        competition, rows = validate(FIXTURE)
        for _ in range(2):
            _, standings, count = load(conn, '?', rows, competition)
        self.assertEqual(count, 2)
        self.assertEqual(standings[0], ('A', 2, 1, 1, 0, 2, 1, 1, 4))
        changed = copy.deepcopy(FIXTURE)
        changed['matches'][0]['date'] = '2024-08-02'
        changed['matches'][0]['score']['ft'] = [0, 3]
        _, rows = validate(changed)
        _, standings, count = load(conn, '?', rows, competition)
        self.assertEqual(count, 2)
        self.assertEqual(standings[0][0], 'B')
        conn.close()

    def test_reject_bad_scores_dates_and_duplicates(self):
        for field, value in [('score', {'ft': [-1, 0]}), ('score', {'ft': [True, 0]}),
                             ('score', {'ft': [1]}), ('date', '2024-99-99'), ('team1', 'B')]:
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(FIXTURE)
                bad['matches'][0][field] = value
                with self.assertRaises(ValueError):
                    validate(bad)
        bad = copy.deepcopy(FIXTURE)
        bad['matches'].append(bad['matches'][0])
        with self.assertRaises(ValueError):
            validate(bad)

    def test_unplayed_match_is_not_a_draw(self):
        data = copy.deepcopy(FIXTURE)
        del data['matches'][1]['score']
        competition, rows = validate(data)
        conn = sqlite3.connect(':memory:')
        _, standings, count = load(conn, '?', rows, competition)
        self.assertEqual(count, 2)
        self.assertEqual(standings[0][1], 1)
        conn.close()

    def test_load_rolls_back_on_database_failure(self):
        conn = sqlite3.connect(':memory:')
        competition, rows = validate(FIXTURE)
        load(conn, '?', rows, competition)
        bad_rows = [tuple([*rows[0][:6], 7, 0]), tuple([*rows[1][:6], -1, 0])]
        with self.assertRaises(sqlite3.IntegrityError):
            load(conn, '?', bad_rows, competition)
        goals = conn.execute('SELECT home_goals FROM matches WHERE match_id=?', (rows[0][0],)).fetchone()[0]
        self.assertEqual(goals, 2)
        conn.close()

    def test_end_to_end_and_invalid_batch_preserves_database(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.json'
            source.write_text(json.dumps(FIXTURE))
            db = str(Path(folder) / 'test.db')
            args = dict(input_file=source, output_dir=folder, sqlite_path=db)
            result = run(**args)
            self.assertEqual(result['stored_matches'], 2)
            self.assertTrue((Path(folder) / 'standings.csv').exists())
            source.write_text('{"name":"Bad","matches":[]}')
            with self.assertRaises(ValueError):
                run(**args)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM matches').fetchone()[0], 2)

    @unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'PostgreSQL integration URL not configured')
    def test_postgres_rerun(self):
        conn, placeholder = connect(os.environ['TEST_DATABASE_URL'], None)
        try:
            competition, rows = validate(FIXTURE)
            load(conn, placeholder, rows, competition)
            _, standings, count = load(conn, placeholder, rows, competition)
            self.assertEqual(count, 2)
            self.assertEqual(standings[0][-1], 4)
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
