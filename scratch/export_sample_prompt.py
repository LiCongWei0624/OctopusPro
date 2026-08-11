# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (
    load_match_store, PREMATCH_STATUSES, _load_ai_runtime_config,
    _prepare_analysis_snapshot, _refresh_required_trend_history,
    build_match_prompt_context, _VERSION_PERSPECTIVES
)

mid = "4560076"
h = "中西部联队"
a = "马科姆联合"

s_ok, s_err, details, snapshot = _prepare_analysis_snapshot(mid, h, a, force_refresh=False)
trends_ok, trend_error, trend_quality = _refresh_required_trend_history(mid, details.get('odds_index', []), 'prematch')
b_ok, b_err, context_str = build_match_prompt_context(mid, h, a, 'prematch', details=details, trend_quality=trend_quality)

ok, config_err, runtime_config = _load_ai_runtime_config()

output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cache', 'sample_match_prompt.txt')

full_prompt = f"""=== SYSTEM PROMPT ===
{runtime_config['system_prompt']}

=== USER PROMPT (版本1: 基本面与战术视角) ===
{_VERSION_PERSPECTIVES[0].format(context_str=context_str)}
"""

with open(output_path, 'w', encoding='utf-8') as f:
    f.write(full_prompt)

print(f"Sample prompt exported to: {output_path} (length: {len(full_prompt)} chars)")
