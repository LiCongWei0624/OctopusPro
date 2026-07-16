"""Immutable pre-match prediction records and simple result settlement."""

import datetime
import hashlib
import json
import sqlite3
from contextlib import closing


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def init_database(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                kickoff TEXT,
                analysis_mode TEXT NOT NULL DEFAULT 'prematch',
                created_at TEXT NOT NULL,
                model_name TEXT NOT NULL,
                competition TEXT,
                fixture_date TEXT,
                fixture_status INTEGER,
                prompt_hash TEXT NOT NULL,
                context_hash TEXT NOT NULL,
                context_text TEXT,
                prediction_json TEXT,
                final_report TEXT NOT NULL,
                settled_at TEXT,
                result_json TEXT
            )
        ''')
        columns = {row[1] for row in conn.execute('PRAGMA table_info(predictions)')}
        if 'analysis_mode' not in columns:
            conn.execute("ALTER TABLE predictions ADD COLUMN analysis_mode TEXT NOT NULL DEFAULT 'prematch'")
        if 'context_text' not in columns:
            conn.execute("ALTER TABLE predictions ADD COLUMN context_text TEXT")
        if 'competition' not in columns:
            conn.execute("ALTER TABLE predictions ADD COLUMN competition TEXT")
        if 'fixture_date' not in columns:
            conn.execute("ALTER TABLE predictions ADD COLUMN fixture_date TEXT")
        if 'fixture_status' not in columns:
            conn.execute("ALTER TABLE predictions ADD COLUMN fixture_status INTEGER")
        conn.commit()


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
    with closing(sqlite3.connect(db_path)) as conn:
        # A backtest sample represents one fixture at one decision point. Re-running
        # the same report must not inflate its apparent accuracy.
        if record:
            existing = conn.execute('''
                SELECT id FROM predictions
                WHERE match_id = ? AND analysis_mode = ? AND prediction_json IS NOT NULL
                LIMIT 1
            ''', (str(metadata['match_id']), metadata.get('analysis_mode', 'prematch'))).fetchone()
            if existing:
                return False
        conn.execute('''
            INSERT INTO predictions (
                match_id, home_team, away_team, kickoff, analysis_mode, created_at, model_name,
                competition, fixture_date, fixture_status, prompt_hash, context_hash, context_text,
                prediction_json, final_report
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(metadata['match_id']), metadata.get('home_team', ''), metadata.get('away_team', ''),
            metadata.get('kickoff', ''), metadata.get('analysis_mode', 'prematch'), _now(), model_name,
            metadata.get('competition', ''), metadata.get('fixture_date', ''), metadata.get('fixture_status'),
            _hash(system_prompt), _hash(context),
            context, json.dumps(record, ensure_ascii=False) if record else None, final_report,
        ))
        conn.commit()
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
    with closing(sqlite3.connect(db_path)) as conn:
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
        conn.commit()
    return settled


def summary(db_path, limit=None):
    markets = {'one_x_two': [], 'asian_handicap': [], 'over_under': []}
    recent = []
    with closing(sqlite3.connect(db_path)) as conn:
        query = '''
            SELECT id, match_id, home_team, away_team, kickoff, analysis_mode, created_at,
                   competition, fixture_date, fixture_status, prediction_json, result_json
            FROM predictions ORDER BY id DESC
        '''
        params = ()
        if limit is not None:
            query += ' LIMIT ?'
            params = (limit,)
        rows = conn.execute(query, params).fetchall()
    for row in rows:
        prediction = json.loads(row[10]) if row[10] else None
        result = json.loads(row[11]) if row[11] else None
        recent.append({
            'id': row[0], 'match_id': row[1], 'home_team': row[2], 'away_team': row[3],
            'kickoff': row[4], 'analysis_mode': row[5], 'created_at': row[6],
            'competition': row[7], 'fixture_date': row[8], 'fixture_status': row[9],
            'prediction': prediction, 'result': result,
        })
        if result:
            for market in markets:
                markets[market].append(result[market])

    overview = {
        'window_size': len(rows),
        'tracked': sum(row[10] is not None for row in rows),
        'settled': sum(row[11] is not None for row in rows),
        'pending': sum(row[10] is not None and row[11] is None for row in rows),
        'untracked': sum(row[10] is None for row in rows),
    }
    by_mode = {}
    for row in rows:
        mode = row[5] or 'prematch'
        bucket = by_mode.setdefault(mode, {'total': 0, 'tracked': 0, 'settled': 0})
        bucket['total'] += 1
        bucket['tracked'] += row[10] is not None
        bucket['settled'] += row[11] is not None

    metrics = {}
    hit_points = {'win': 1.0, 'half_win': 0.5, 'push': 0.0, 'half_loss': 0.0, 'loss': 0.0}
    for market, outcomes in markets.items():
        outcome_counts = {
            outcome: sum(item.get('outcome') == outcome for item in outcomes)
            for outcome in hit_points
        }
        if market == 'one_x_two':
            wins = outcome_counts['win']
            metrics[market] = {
                'settled': len(outcomes), 'wins': wins,
                'losses': outcome_counts['loss'],
                'hit_rate': round(wins / len(outcomes), 4) if outcomes else None,
            }
            continue
        points = sum(hit_points[item['outcome']] for item in outcomes)
        units = sum(item['unit_return'] for item in outcomes)
        metrics[market] = {
            'settled': len(outcomes),
            'hit_rate': round(points / len(outcomes), 4) if outcomes else None,
            'settlement_units': round(units, 2),
            'wins': outcome_counts['win'],
            'half_wins': outcome_counts['half_win'],
            'pushes': outcome_counts['push'],
            'half_losses': outcome_counts['half_loss'],
            'losses': outcome_counts['loss'],
        }
    return {'overview': overview, 'by_mode': by_mode, 'metrics': metrics, 'recent': recent}


def prediction_detail(db_path, prediction_id):
    """Return one immutable backtest sample without loading every report into the list view."""
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute('''
            SELECT id, match_id, home_team, away_team, kickoff, analysis_mode, created_at,
                   model_name, competition, fixture_date, fixture_status, context_text,
                   prediction_json, final_report, settled_at, result_json
            FROM predictions WHERE id = ?
        ''', (prediction_id,)).fetchone()

    if not row:
        return None

    return {
        'id': row[0],
        'match_id': row[1],
        'home_team': row[2],
        'away_team': row[3],
        'kickoff': row[4],
        'analysis_mode': row[5],
        'created_at': row[6],
        'model_name': row[7],
        'competition': row[8],
        'fixture_date': row[9],
        'fixture_status': row[10],
        'context': row[11],
        'prediction': json.loads(row[12]) if row[12] else None,
        'final_report': row[13],
        'settled_at': row[14],
        'result': json.loads(row[15]) if row[15] else None,
    }
