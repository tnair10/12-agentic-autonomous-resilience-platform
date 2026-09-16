import argparse
import json
from pathlib import Path

def load_json(path):
    return json.loads(Path(path).read_text())

def historical_priors(history, threshold):
    eligible = []
    weights = {}
    total_weight = 0.0
    for incident in history.get('similar_incidents', []):
        similarity = float(incident.get('similarity', 0))
        if similarity < threshold:
            continue
        root = incident.get('ai_root_cause') or incident.get('causal_root')
        if not root:
            continue
        confidence = float(incident.get('ai_confidence') or 0.5)
        weight = similarity * confidence
        weights[root] = weights.get(root, 0.0) + weight
        total_weight += weight
        eligible.append(incident)
    priors = {}
    if total_weight > 0:
        for root, weight in weights.items():
            priors[root] = weight / total_weight
    return (eligible, priors)

def strongest_similarity(eligible, root):
    values = []
    for incident in eligible:
        incident_root = incident.get('ai_root_cause') or incident.get('causal_root')
        if incident_root == root:
            values.append(float(incident.get('similarity', 0)))
    return max(values, default=0.0)

def fuse(hypotheses, causal, history, threshold):
    causal_root = causal.get('causal_root_signal')
    eligible, priors = historical_priors(history, threshold)
    rankings = []
    for hypothesis in hypotheses.get('hypotheses', []):
        name = hypothesis['hypothesis']
        live_confidence = float(hypothesis.get('confidence', 0))
        causal_bonus = 0.1 if name == causal_root else 0.0
        causal_penalty = 0.05 if causal_root and name != causal_root else 0.0
        history_prior = float(priors.get(name, 0))
        history_similarity = strongest_similarity(eligible, name)
        history_bonus = 0.12 * history_prior * history_similarity
        fused_score = live_confidence + causal_bonus + history_bonus - causal_penalty
        fused_score = max(0.0, min(1.0, fused_score))
        rankings.append({'hypothesis': name, 'live_confidence': round(live_confidence, 4), 'causal_agreement': name == causal_root, 'causal_bonus': round(causal_bonus, 4), 'causal_penalty': round(causal_penalty, 4), 'historical_prior': round(history_prior, 4), 'historical_similarity': round(history_similarity, 4), 'historical_bonus': round(history_bonus, 4), 'fused_score': round(fused_score, 4)})
    rankings.sort(key=lambda item: item['fused_score'], reverse=True)
    for index, item in enumerate(rankings, start=1):
        item['rank'] = index
    return {'causal_root': causal_root, 'memory_similarity_threshold': threshold, 'historical_matches_total': len(history.get('similar_incidents', [])), 'historical_matches_used': len(eligible), 'memory_gate_status': 'ACTIVE' if eligible else 'NO_TRUSTED_MATCH', 'rankings': rankings, 'final_root_cause': rankings[0]['hypothesis'] if rankings else None, 'final_confidence': rankings[0]['fused_score'] if rankings else 0}

def main():
    parser = argparse.ArgumentParser(description='Project 12 evidence fusion agent')
    parser.add_argument('--hypotheses', default='results/incidents/latest-hypotheses.json')
    parser.add_argument('--causal', default='results/incidents/latest-causal-analysis.json')
    parser.add_argument('--history', default='results/incidents/latest-history.json')
    parser.add_argument('--memory-threshold', type=float, default=0.85)
    parser.add_argument('--output', default='results/incidents/latest-fusion.json')
    args = parser.parse_args()
    result = fuse(load_json(args.hypotheses), load_json(args.causal), load_json(args.history), args.memory_threshold)
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print()
    print(f'FUSION_WRITTEN={args.output}')
    print('FUSION_AGENT=PASS')
if __name__ == '__main__':
    main()
