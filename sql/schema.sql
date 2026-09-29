CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY, competition TEXT NOT NULL, round TEXT NOT NULL,
    match_date TEXT NOT NULL, home_team TEXT NOT NULL, away_team TEXT NOT NULL,
    home_goals INTEGER, away_goals INTEGER,
    CHECK(home_team <> away_team),
    CHECK(home_goals >= 0 AND away_goals >= 0),
    CHECK((home_goals IS NULL) = (away_goals IS NULL))
);
