-- Replace the competition literal to query another season.
WITH performances AS (
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
FROM performances WHERE competition = 'English Premier League 2024/25'
GROUP BY team ORDER BY points DESC, goal_difference DESC, goals_for DESC, team;
