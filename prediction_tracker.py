"""Immutable pre-match prediction records and simple result settlement."""

import datetime
import hashlib
import json
import sqlite3


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def init_database(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                kickoff TEXT,
                created_at TEXT NOT NULL,
                model_name TEXT NOT NULL,
                prompt_hash TEXT NOT NULL,
                context_hash TEXT NOT NULL,
                prediction_json TEXT,
                final_report TEXT NOT NULL,
                settled_at TEXT,
                result_json TEXT
            )
        ''')


def _prediction_record_from_text(report):
    """Read the last valid JSON object containing prediction_record."""
    decoder = json.JSONDecoder()
    found = []
    for index, char in enumerate(report or ''):
        if char != '{':
            continue
        try:
            value, _ = decoder.raw_decode(report[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get('prediction_record'), dict):
            found.append(value['prediction_record'])
    return found[-1] if found else None


def _normalise_prediction(record):
    if not isinstance(record, dict):
        return None
    one_x_two = record.get('one_x_two')
    handicap = record.get('asian_handicap')
    over_under = record.get('over_under')
    confidence = record.get('confidence', 'low')

    if one_x_two not in {'home', 'draw', 'away'}:
        return None
    if not isinstance(handicap, dict) or handicap.get('team') not in {'home', 'away'}:
        return None
    if not isinstance(over_under, dict) or over_under.get('side') not in {'over', 'under'}:
        return None
    try:
        handicap_line = float(handicap['line'])
        total_line = float(over_under['line'])
    except (KeyError, TypeError, ValueError):
        return None
    if confidence not in {'high', 'medium', 'low'}:
        confidence = 'low'
    return {
        'one_x_two': one_x_two,
        'asian_handicap': {'team': handicap['team'], 'line': handicap_line},
        'over_under': {'side': over_under['side'], 'line': total_line},
        'confidence': confidence,
    }


def record_prediction(db_path, metadata, model_name, system_prompt, context, final_report):
    record = _normalise_prediction(_prediction_record_from_text(final_report))
    with sqlite3.connect(db_path) as conn:
        conn.execute('''
            INSERT INTO predictions (
                match_id, home_team, away_team, kickoff, created_at, model_name,
                prompt_hash, context_hash, prediction_json, final_report
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(metadata['match_id']), metadata.get('home_team', ''), metadata.get('away_team', ''),
            metadata.get('kickoff', ''), _now(), model_name, _hash(system_prompt), _hash(context),
            json.dumps(record, ensure_ascii=False) if record else None, final_report,
        ))
    return record is not None


def _score(score):
    try:
        home, away = score.replace(':', '-').split('-', 1)
        return int(home.strip()), int(away.strip())
    except (AttributeError, ValueError):
        return None


def _quarter_lines(line):
    # Quarter balls are two equal half-stakes; all other Asian lines are one stake.
    quarter = round(line * 4)
    return [line - 0.25, line + 0.25] if abs(quarter) % 2 else [line]


def _settle_values(values):
    units = []
    for value in values:
        units.append(1.0 if value > 1e-9 else -1.0 if value < -1e-9 else 0.0)
    unit_return = sum(units) / len(units)
    if unit_return >= 0.99:
        outcome = 'win'
    elif unit_return > 0.01:
        outcome = 'half_win'
    elif unit_return <= -0.99:
        outcome = 'loss'
    elif unit_return < -0.01:
        outcome = 'half_loss'
    else:
        outcome = 'push'
    return {'outcome': outcome, 'unit_return': unit_return}


def _settle_prediction(prediction, home_goals, away_goals):
    one_x_two = prediction['one_x_two']
    actual = 'home' if home_goals > away_goals else 'away' if away_goals > home_goals else 'draw'
    handicap = prediction['asian_handicap']
    team_diff = home_goals - away_goals if handicap['team'] == 'home' else away_goals - home_goals
    handicap_result = _settle_values([team_diff + line for line in _quarter_lines(handicap['line'])])
    totals = prediction['over_under']
    goals = home_goals + away_goals
    if totals['side'] == 'over':
        total_values = [goals - line for line in _quarter_lines(totals['line'])]
    else:
        total_values = [line - goals for line in _quarter_lines(totals['line'])]
    totals_result = _settle_values(total_values)
    return {
        'score': f'{home_goals}-{away_goals}',
        'one_x_two': {'outcome': 'win' if one_x_two == actual else 'loss'},
        'asian_handicap': handicap_result,
        'over_under': totals_result,
    }


def settle_finished_predictions(db_path, matches):
    by_id = {str(match.get('id')): match for match in matches}
    settled = 0
    with sqlite3.connect(db_path) as conn:
        pending = conn.execute('''
            SELECT id, match_id, prediction_json FROM predictions
            WHERE result_json IS NULL AND prediction_json IS NOT NULL
        ''').fetchall()
        for prediction_id, match_id, prediction_json in pending:
            match = by_id.get(str(match_id), {})
            if int(match.get('status', 0) or 0) != 8:
                continue
            score = _score(match.get('score', ''))
            if not score:
                continue
            result = _settle_prediction(json.loads(prediction_json), *score)
            conn.execute(
                'UPDATE predictions SET settled_at = ?, result_json = ? WHERE id = ?',
                (_now(), json.dumps(result, ensure_ascii=False), prediction_id),
            )
            settled += 1
    return settled


def summary(db_path, limit=100):
    markets = {'one_x_two': [], 'asian_handicap': [], 'over_under': []}
    recent = []
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute('''
            SELECT id, match_id, home_team, away_team, kickoff, created_at,
                   prediction_json, result_json
            FROM predictions ORDER BY id DESC LIMIT ?
        ''', (limit,)).fetchall()
    for row in rows:
        prediction = json.loads(row[6]) if row[6] else None
        result = json.loads(row[7]) if row[7] else None
        recent.append({
            'id': row[0], 'match_id': row[1], 'home_team': row[2], 'away_team': row[3],
            'kickoff': row[4], 'created_at': row[5], 'prediction': prediction, 'result': result,
        })
        if result:
            for market in markets:
                markets[market].append(result[market])

    metrics = {}
    hit_points = {'win': 1.0, 'half_win': 0.5, 'push': 0.0, 'half_loss': 0.0, 'loss': 0.0}
    for market, outcomes in markets.items():
        if market == 'one_x_two':
            wins = sum(item['outcome'] == 'win' for item in outcomes)
            metrics[market] = {'settled': len(outcomes), 'wins': wins,
                               'hit_rate': round(wins / len(outcomes), 4) if outcomes else None}
            continue
        points = sum(hit_points[item['outcome']] for item in outcomes)
        units = sum(item['unit_return'] for item in outcomes)
        metrics[market] = {
            'settled': len(outcomes),
            'hit_rate': round(points / len(outcomes), 4) if outcomes else None,
            'settlement_units': round(units, 2),
        }
    return {'metrics': metrics, 'recent': recent}
