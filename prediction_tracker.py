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


def _line_is_offered(line, offered_lines):
    return not offered_lines or any(abs(float(line) - float(offered)) < 1e-6 for offered in offered_lines)


def _snapshot_quote(market_catalog, market, side_key, side, line):
    quotes = (market_catalog or {}).get(market, {}).get('quotes', [])
    matching = [
        quote for quote in quotes
        if quote.get(side_key) == side and abs(float(quote.get('line', 999)) - float(line)) < 1e-6
    ]
    if not matching:
        return None
    # The middle price avoids treating one company as a representative market.
    quote = sorted(matching, key=lambda item: float(item.get('water', 0)))[len(matching) // 2]
    return {
        'company': quote.get('company', ''),
        'cid': str(quote.get('cid', '')),
        'water': float(quote['water']),
        'decimal_odds': float(quote['decimal_odds']),
        'market_probability': quote.get('market_probability'),
        'baseline_ev': quote.get('baseline_ev'),
    }


def _normalise_prediction(record, market_catalog=None):
    if not isinstance(record, dict):
        return None
    one_x_two = record.get('one_x_two')
    handicap = record.get('asian_handicap')
    over_under = record.get('over_under')
    confidence = record.get('confidence', 'low')
    status = record.get('status', 'bet')

    # New predictions track only Asian handicap and totals. Keep the optional
    # legacy 1X2 field readable so previously stored reports remain settleable.
    if one_x_two is not None and one_x_two not in {'home', 'draw', 'away'}:
        return None
    if status not in {'bet', 'no_bet'}:
        return None
    if confidence not in {'high', 'medium', 'low'}:
        confidence = 'low'
    normalised = {
        'status': status,
        'confidence': confidence,
        'reason': str(record.get('reason', '')).strip()[:240],
    }
    if status == 'no_bet':
        if handicap is not None or over_under is not None:
            return None
        return normalised

    if isinstance(handicap, dict):
        if handicap.get('team') not in {'home', 'away'}:
            return None
        try:
            normalised['asian_handicap'] = {
                'team': handicap['team'], 'line': float(handicap['line']),
            }
        except (KeyError, TypeError, ValueError):
            return None
        offered = (market_catalog or {}).get('asian_handicap', {}).get(handicap['team'], [])
        if not _line_is_offered(normalised['asian_handicap']['line'], offered):
            return None
        quote = _snapshot_quote(
            market_catalog, 'asian_handicap', 'team', handicap['team'], normalised['asian_handicap']['line']
        )
        if quote:
            normalised['asian_handicap']['quote'] = quote
    elif handicap is not None:
        return None

    if isinstance(over_under, dict):
        if over_under.get('side') not in {'over', 'under'}:
            return None
        try:
            normalised['over_under'] = {
                'side': over_under['side'], 'line': float(over_under['line']),
            }
        except (KeyError, TypeError, ValueError):
            return None
        offered = (market_catalog or {}).get('over_under', {}).get('line', [])
        if not _line_is_offered(normalised['over_under']['line'], offered):
            return None
        quote = _snapshot_quote(
            market_catalog, 'over_under', 'side', over_under['side'], normalised['over_under']['line']
        )
        if quote:
            normalised['over_under']['quote'] = quote
    elif over_under is not None:
        return None

    if not any(market in normalised for market in ('asian_handicap', 'over_under')):
        return None
    if one_x_two is not None:
        normalised['one_x_two'] = one_x_two
    return normalised


def record_prediction(db_path, metadata, model_name, system_prompt, context, final_report):
    record = _normalise_prediction(
        _prediction_record_from_text(final_report), metadata.get('market_catalog')
    )
    if record:
        record['strategy_version'] = metadata.get('strategy_version', 'legacy')
        record['tracking_cohort_id'] = metadata.get('tracking_cohort_id', record['strategy_version'])
        record['tracking_cohort_name'] = metadata.get('tracking_cohort_name', '')
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


def _settle_values(values, win_return=1.0, quoted=False):
    units = []
    settlement_units = []
    for value in values:
        settlement_units.append(1.0 if value > 1e-9 else -1.0 if value < -1e-9 else 0.0)
        units.append(win_return if value > 1e-9 else -1.0 if value < -1e-9 else 0.0)
    unit_return = sum(units) / len(units)
    settlement_return = sum(settlement_units) / len(settlement_units)
    if settlement_return >= 0.99:
        outcome = 'win'
    elif settlement_return > 0.01:
        outcome = 'half_win'
    elif settlement_return <= -0.99:
        outcome = 'loss'
    elif settlement_return < -0.01:
        outcome = 'half_loss'
    else:
        outcome = 'push'
    return {'outcome': outcome, 'unit_return': unit_return, 'quoted': quoted}


def _settle_prediction(prediction, home_goals, away_goals):
    result = {'score': f'{home_goals}-{away_goals}'}
    handicap = prediction.get('asian_handicap')
    if handicap:
        team_diff = home_goals - away_goals if handicap['team'] == 'home' else away_goals - home_goals
        quote = handicap.get('quote') or {}
        result['asian_handicap'] = _settle_values(
            [team_diff + line for line in _quarter_lines(handicap['line'])],
            float(quote.get('water', 1.0)), bool(quote),
        )
    totals = prediction.get('over_under')
    if totals:
        goals = home_goals + away_goals
        quote = totals.get('quote') or {}
        if totals['side'] == 'over':
            total_values = [goals - line for line in _quarter_lines(totals['line'])]
        else:
            total_values = [line - goals for line in _quarter_lines(totals['line'])]
        result['over_under'] = _settle_values(total_values, float(quote.get('water', 1.0)), bool(quote))
    if prediction.get('one_x_two') in {'home', 'draw', 'away'}:
        actual = 'home' if home_goals > away_goals else 'away' if away_goals > home_goals else 'draw'
        result['one_x_two'] = {'outcome': 'win' if prediction['one_x_two'] == actual else 'loss'}
    return result


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


def _cohort_identity(prediction):
    prediction = prediction or {}
    cohort_id = str(prediction.get('tracking_cohort_id', '')).strip()
    cohort_name = str(prediction.get('tracking_cohort_name', '')).strip()
    if cohort_id:
        return cohort_id, cohort_name or cohort_id
    if prediction.get('strategy_version') == 'dual-market-v2':
        return 'dual-market-v2-unassigned', '双市场 v2（未分批旧记录）'
    return 'legacy', '历史记录（旧策略）'


def summary(db_path, limit=None, cohort_id=None, cohort_definitions=None):
    markets = {'asian_handicap': [], 'over_under': []}
    recent = []
    cohort_catalog = {}
    for cohort in cohort_definitions or []:
        if not isinstance(cohort, dict):
            continue
        defined_id = str(cohort.get('id', '')).strip()
        defined_name = str(cohort.get('name', '')).strip()
        if defined_id and defined_name:
            cohort_catalog[defined_id] = defined_name
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
        sample_cohort_id, sample_cohort_name = _cohort_identity(prediction)
        cohort_catalog.setdefault(sample_cohort_id, sample_cohort_name)
        recent[-1]['tracking_cohort_id'] = sample_cohort_id
        recent[-1]['tracking_cohort_name'] = sample_cohort_name

    selected_cohort_id = cohort_id if cohort_id in cohort_catalog else None
    if selected_cohort_id:
        recent = [sample for sample in recent if sample['tracking_cohort_id'] == selected_cohort_id]

    breakdowns = {
        'strategy': {'asian_handicap': {}, 'over_under': {}},
        'line': {'asian_handicap': {}, 'over_under': {}},
        'competition': {'asian_handicap': {}, 'over_under': {}},
    }
    for sample in recent:
        prediction = sample['prediction'] or {}
        result = sample['result'] or {}
        for market in markets:
            if not result.get(market):
                continue
            markets[market].append(result[market])
            prediction_market = prediction.get(market, {})
            strategy_key = ' | '.join([
                prediction.get('strategy_version', 'legacy'),
                sample['analysis_mode'] or 'prematch',
                prediction.get('confidence', 'low'),
            ])
            line = prediction_market.get('line')
            line_key = f'{line:+g}' if isinstance(line, (int, float)) else 'unknown'
            competition_key = sample['competition'] or 'unclassified'
            for kind, key in (
                ('strategy', strategy_key), ('line', line_key), ('competition', competition_key),
            ):
                breakdowns[kind][market].setdefault(key, []).append(result[market])

    recommended = [sample for sample in recent if sample['prediction'] and sample['prediction'].get('status', 'bet') == 'bet']
    no_bet = [sample for sample in recent if sample['prediction'] and sample['prediction'].get('status') == 'no_bet']
    overview = {
        'window_size': len(recent),
        'tracked': sum(sample['prediction'] is not None for sample in recent),
        'recommended': len(recommended),
        'no_bet': len(no_bet),
        'settled': sum(sample['result'] is not None for sample in recommended),
        'pending': sum(sample['result'] is None for sample in recommended),
        'untracked': sum(sample['prediction'] is None for sample in recent),
    }
    by_mode = {}
    for sample in recent:
        mode = sample['analysis_mode'] or 'prematch'
        bucket = by_mode.setdefault(mode, {'total': 0, 'tracked': 0, 'settled': 0})
        bucket['total'] += 1
        bucket['tracked'] += sample['prediction'] is not None
        bucket['settled'] += sample['result'] is not None

    hit_points = {'win': 1.0, 'half_win': 0.5, 'push': 0.0, 'half_loss': 0.0, 'loss': 0.0}

    def metric_for(outcomes):
        outcome_counts = {
            outcome: sum(item.get('outcome') == outcome for item in outcomes)
            for outcome in hit_points
        }
        points = sum(hit_points[item['outcome']] for item in outcomes)
        decisive = sum(item.get('outcome') != 'push' for item in outcomes)
        priced_outcomes = [item for item in outcomes if item.get('quoted')]
        return {
            'settled': len(outcomes),
            'decisive': decisive,
            'hit_rate': round(points / decisive, 4) if decisive else None,
            'effective_wins': round(points, 2),
            'priced_settled': len(priced_outcomes),
            'roi': round(sum(item['unit_return'] for item in priced_outcomes) / len(priced_outcomes), 4) if priced_outcomes else None,
            'wins': outcome_counts['win'],
            'half_wins': outcome_counts['half_win'],
            'pushes': outcome_counts['push'],
            'half_losses': outcome_counts['half_loss'],
            'losses': outcome_counts['loss'],
        }

    metrics = {market: metric_for(outcomes) for market, outcomes in markets.items()}
    breakdown_metrics = {
        kind: {
            market: [
                {'key': key, **metric_for(outcomes)}
                for key, outcomes in sorted(groups.items())
            ]
            for market, groups in markets_by_group.items()
        }
        for kind, markets_by_group in breakdowns.items()
    }
    return {
        'overview': overview, 'by_mode': by_mode, 'metrics': metrics,
        'breakdowns': breakdown_metrics, 'recent': recent,
        'cohorts': [
            {'id': known_id, 'name': known_name, 'selected': known_id == selected_cohort_id}
            for known_id, known_name in cohort_catalog.items()
        ],
        'selected_cohort_id': selected_cohort_id,
    }


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
