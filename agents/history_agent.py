import argparse
import json
import math
import sqlite3
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data' / 'incidents' / 'incident_memory.db'

def load_json(path):
    return json.loads(Path(path).read_text())

def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def metric(telemetry, name, field):
    value = telemetry.get('metrics', {}).get(name, {}).get(field)
    if value is None:
        return 0.0
    return float(value)

def build_features(telemetry):
    latency = metric(telemetry, 'latency_ms', 'peak')
    error_rate = metric(telemetry, 'error_rate', 'peak')
    consumer_lag = metric(telemetry, 'consumer_lag', 'peak')
    queue_depth = metric(telemetry, 'queue_depth', 'peak')
    db_latency = metric(telemetry, 'database_latency_ms', 'peak')
    tls_delta = metric(telemetry, 'tls_failures', 'delta')
    auth_delta = metric(telemetry, 'authentication_failures', 'delta')
    retry_delta = metric(telemetry, 'retry_count', 'delta')
    gc_delta = metric(telemetry, 'young_gc_count', 'delta')
    heap_peak = metric(telemetry, 'heap_used_bytes', 'peak')
    heap_max = metric(telemetry, 'heap_max_bytes', 'current')
    heap_ratio = heap_peak / heap_max if heap_max > 0 else 0.0
    ratios = np.array([min(latency / 500.0, 5.0), min(error_rate / 0.05, 5.0), min(consumer_lag / 1000.0, 5.0), min(queue_depth / 50.0, 5.0), min(db_latency / 500.0, 5.0), min(tls_delta / 100.0, 5.0), min(auth_delta / 100.0, 5.0), min(retry_delta / 100.0, 5.0), min(gc_delta / 3.0, 5.0), min(heap_ratio / 0.7, 5.0)], dtype=float)
    flags = {'latency_spike': latency >= 500, 'error_spike': error_rate >= 0.05, 'consumer_lag_spike': consumer_lag >= 1000, 'queue_depth_spike': queue_depth >= 50, 'database_latency_spike': db_latency >= 500, 'tls_failures': tls_delta > 0, 'authentication_failures': auth_delta > 0, 'retry_storm': retry_delta >= 100, 'gc_pressure': gc_delta >= 3, 'heap_pressure': heap_ratio >= 0.7}
    return {'vector': ratios, 'flags': flags, 'raw': {'latency_peak_ms': latency, 'error_rate_peak': error_rate, 'consumer_lag_peak': consumer_lag, 'queue_depth_peak': queue_depth, 'database_latency_peak_ms': db_latency, 'tls_failure_delta': tls_delta, 'authentication_failure_delta': auth_delta, 'retry_delta': retry_delta, 'gc_delta': gc_delta, 'heap_ratio': heap_ratio}}

def cosine_similarity(left, right):
    left_norm = np.linalg.norm(left)
    right_norm = np.linalg.norm(right)
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))

def jaccard_similarity(left_flags, right_flags):
    left = {key for key, value in left_flags.items() if value}
    right = {key for key, value in right_flags.items() if value}
    union = left | right
    if not union:
        return 1.0
    intersection = left & right
    return len(intersection) / len(union)

def combined_similarity(current, historical):
    cosine = cosine_similarity(current['vector'], historical['vector'])
    jaccard = jaccard_similarity(current['flags'], historical['flags'])
    score = cosine * 0.7 + jaccard * 0.3
    return {'similarity': round(score, 4), 'cosine_similarity': round(cosine, 4), 'signal_overlap': round(jaccard, 4)}

def load_history(connection):
    rows = connection.execute('\n        SELECT\n            incident_id,\n            scenario,\n            ai_root_cause,\n            causal_root,\n            ai_confidence,\n            recovery_status,\n            remediation,\n            remediation_success,\n            operator_feedback,\n            raw_record\n        FROM incidents\n        ORDER BY created_at DESC\n        ').fetchall()
    history = []
    for row in rows:
        raw = json.loads(row['raw_record'])
        telemetry = raw.get('telemetry', {})
        history.append({'incident_id': row['incident_id'], 'scenario': row['scenario'], 'ai_root_cause': row['ai_root_cause'], 'causal_root': row['causal_root'], 'ai_confidence': row['ai_confidence'], 'recovery_status': row['recovery_status'], 'remediation': row['remediation'], 'remediation_success': row['remediation_success'], 'operator_feedback': row['operator_feedback'], 'features': build_features(telemetry)})
    return history

def build_priors(matches):
    weights = {}
    total_weight = 0.0
    for match in matches:
        root = match.get('ai_root_cause') or match.get('causal_root')
        if not root:
            continue
        weight = match['similarity'] * float(match.get('ai_confidence') or 0.5)
        weights[root] = weights.get(root, 0.0) + weight
        total_weight += weight
    if total_weight == 0:
        return []
    priors = []
    for root, weight in weights.items():
        priors.append({'root_cause': root, 'historical_prior': round(weight / total_weight, 4)})
    priors.sort(key=lambda item: item['historical_prior'], reverse=True)
    return priors

def investigate(telemetry, top_k):
    current = build_features(telemetry)
    connection = connect()
    history = load_history(connection)
    matches = []
    for incident in history:
        similarity = combined_similarity(current, incident['features'])
        match = {'incident_id': incident['incident_id'], 'scenario': incident['scenario'], 'ai_root_cause': incident['ai_root_cause'], 'causal_root': incident['causal_root'], 'ai_confidence': incident['ai_confidence'], 'recovery_status': incident['recovery_status'], 'remediation': incident['remediation'], 'remediation_success': incident['remediation_success'], 'operator_feedback': incident['operator_feedback'], **similarity}
        matches.append(match)
    matches.sort(key=lambda item: item['similarity'], reverse=True)
    matches = matches[:top_k]
    return {'historical_incident_count': len(history), 'current_features': {'flags': current['flags'], 'raw': current['raw']}, 'similar_incidents': matches, 'root_cause_priors': build_priors(matches)}

def main():
    parser = argparse.ArgumentParser(description='Project 12 historical incident similarity agent')
    parser.add_argument('--telemetry', default='results/incidents/latest-telemetry.json')
    parser.add_argument('--top-k', type=int, default=5)
    parser.add_argument('--output', default='results/incidents/latest-history.json')
    args = parser.parse_args()
    if not DB_PATH.exists():
        raise SystemExit(f'Incident memory DB missing: {DB_PATH}')
    telemetry = load_json(args.telemetry)
    result = investigate(telemetry, args.top_k)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print()
    print(f'HISTORY_WRITTEN={output}')
    print('HISTORY_AGENT=PASS')
if __name__ == '__main__':
    main()
