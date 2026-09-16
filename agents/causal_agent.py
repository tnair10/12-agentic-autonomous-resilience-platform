import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import networkx as nx
import requests
PROMETHEUS = 'http://127.0.0.1:9090'
SCRAPE_TOLERANCE_SECONDS = 10
SIGNALS = {'tls_failure': {'metric': 'com_project12_workloadmetrics_tlsfailures', 'type': 'counter'}, 'authentication_failure': {'metric': 'com_project12_workloadmetrics_authenticationfailures', 'type': 'counter'}, 'retry_storm': {'metric': 'com_project12_workloadmetrics_retrycount', 'type': 'counter'}, 'high_latency': {'metric': 'com_project12_workloadmetrics_latencyms', 'type': 'gauge', 'threshold': 500}, 'high_error_rate': {'metric': 'com_project12_workloadmetrics_errorrate', 'type': 'gauge', 'threshold': 0.05}, 'consumer_lag': {'metric': 'com_project12_workloadmetrics_consumerlag', 'type': 'gauge', 'threshold': 1000}, 'queue_growth': {'metric': 'com_project12_workloadmetrics_queuedepth', 'type': 'gauge', 'threshold': 50}, 'database_latency': {'metric': 'com_project12_workloadmetrics_databaselatencyms', 'type': 'gauge', 'threshold': 500}, 'gc_storm': {'metric': 'increase(java_lang_g1_young_generation_collectioncount[45s])', 'type': 'gauge', 'threshold': 3}, 'jvm_memory_pressure': {'metric': '100 * java_lang_memory_heapmemoryusage_used / java_lang_memory_heapmemoryusage_max', 'type': 'gauge', 'threshold': 70}}
CAUSAL_EDGES = [('tls_failure', 'retry_storm', 'TLS failures trigger client retries'), ('tls_failure', 'high_error_rate', 'TLS handshake failures create request errors'), ('retry_storm', 'queue_growth', 'Retries increase queued work'), ('queue_growth', 'consumer_lag', 'Backpressure increases consumer lag'), ('consumer_lag', 'high_latency', 'Backlog increases end-to-end latency'), ('retry_storm', 'high_latency', 'Retry amplification increases latency'), ('authentication_failure', 'retry_storm', 'Authentication failures trigger retries'), ('authentication_failure', 'high_error_rate', 'Authentication rejection creates errors'), ('database_latency', 'queue_growth', 'Slow downstream database creates queue buildup'), ('database_latency', 'high_latency', 'Database latency propagates upstream'), ('jvm_memory_pressure', 'gc_storm', 'Heap pressure can increase garbage-collection activity'), ('jvm_memory_pressure', 'high_latency', 'Heap pressure can increase request latency'), ('gc_storm', 'high_latency', 'Excessive garbage collection can increase request latency'), ('gc_storm', 'retry_storm', 'GC-induced latency can trigger retries')]

def parse_window(value):
    unit = value[-1]
    amount = int(value[:-1])
    multipliers = {'s': 1, 'm': 60, 'h': 3600}
    if unit not in multipliers:
        raise ValueError(f'Unsupported window: {value}')
    return amount * multipliers[unit]

def query_range(expression, window_seconds, step=5):
    end = time.time()
    start = end - window_seconds
    response = requests.get(f'{PROMETHEUS}/api/v1/query_range', params={'query': expression, 'start': start, 'end': end, 'step': step}, timeout=10)
    response.raise_for_status()
    payload = response.json()
    results = payload.get('data', {}).get('result', [])
    if not results:
        return []
    return [(float(timestamp), float(value)) for timestamp, value in results[0]['values']]

def timestamp_string(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()

def detect_counter_event(samples):
    if len(samples) < 2:
        return None
    for index in range(1, len(samples)):
        previous = samples[index - 1][1]
        current = samples[index][1]
        if current > previous:
            return {'timestamp': samples[index][0], 'value_before': previous, 'value_after': current, 'delta': current - previous}
    return None

def detect_gauge_event(samples, threshold):
    for timestamp, value in samples:
        if value >= threshold:
            return {'timestamp': timestamp, 'value': value, 'threshold': threshold}
    return None

def collect_events(window_seconds):
    events = {}
    for name, definition in SIGNALS.items():
        samples = query_range(definition['metric'], window_seconds)
        if definition['type'] == 'counter':
            event = detect_counter_event(samples)
        else:
            event = detect_gauge_event(samples, definition['threshold'])
        if event:
            event['signal'] = name
            event['metric'] = definition['metric']
            event['timestamp_iso'] = timestamp_string(event['timestamp'])
            events[name] = event
    return events

def build_graph(events):
    graph = nx.DiGraph()
    for signal in events:
        graph.add_node(signal)
    causal_links = []
    for source, target, reason in CAUSAL_EDGES:
        if source not in events or target not in events:
            continue
        source_time = events[source]['timestamp']
        target_time = events[target]['timestamp']
        observed_delay = target_time - source_time
        tolerance_applied = observed_delay < 0 and abs(observed_delay) <= SCRAPE_TOLERANCE_SECONDS
        if source_time <= target_time + SCRAPE_TOLERANCE_SECONDS:
            graph.add_edge(source, target, reason=reason)
            causal_links.append({'source': source, 'target': target, 'reason': reason, 'source_time': events[source]['timestamp_iso'], 'target_time': events[target]['timestamp_iso'], 'delay_seconds': round(observed_delay, 2), 'tolerance_applied': tolerance_applied, 'scrape_tolerance_seconds': SCRAPE_TOLERANCE_SECONDS})
    return (graph, causal_links)

def rank_root_candidates(graph, events):
    candidates = []
    for node in graph.nodes:
        incoming = graph.in_degree(node)
        outgoing = graph.out_degree(node)
        candidates.append({'signal': node, 'incoming_edges': incoming, 'outgoing_edges': outgoing, 'timestamp': events[node]['timestamp_iso'], 'root_score': outgoing * 2 - incoming * 2})
    candidates.sort(key=lambda item: (item['root_score'], -events[item['signal']]['timestamp']), reverse=True)
    return candidates

def build_paths(graph, root):
    paths = []
    for target in graph.nodes:
        if target == root:
            continue
        if nx.has_path(graph, root, target):
            path = nx.shortest_path(graph, root, target)
            paths.append(path)
    paths.sort(key=len, reverse=True)
    return paths

def main():
    parser = argparse.ArgumentParser(description='Project 12 temporal causal reasoning agent')
    parser.add_argument('--window', default='15m')
    parser.add_argument('--hypotheses', default='results/incidents/latest-hypotheses.json')
    parser.add_argument('--output', default='results/incidents/latest-causal-analysis.json')
    args = parser.parse_args()
    window_seconds = parse_window(args.window)
    events = collect_events(window_seconds)
    graph, links = build_graph(events)
    root_candidates = rank_root_candidates(graph, events)
    root_signal = None
    if root_candidates:
        root_signal = root_candidates[0]['signal']
    hypothesis_data = {}
    hypothesis_path = Path(args.hypotheses)
    if hypothesis_path.exists():
        hypothesis_data = json.loads(hypothesis_path.read_text())
    top_hypothesis = hypothesis_data.get('top_hypothesis', {}).get('hypothesis')
    causal_paths = []
    if root_signal:
        causal_paths = build_paths(graph, root_signal)
    timeline = sorted([{'signal': name, 'timestamp': event['timestamp_iso']} for name, event in events.items()], key=lambda item: events[item['signal']]['timestamp'])
    result = {'window': args.window, 'events_detected': events, 'timeline': timeline, 'causal_links': links, 'root_candidates': root_candidates, 'causal_root_signal': root_signal, 'top_hypothesis': top_hypothesis, 'hypothesis_causal_agreement': root_signal == top_hypothesis, 'causal_paths': causal_paths}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print()
    print(f'CAUSAL_ANALYSIS_WRITTEN={output}')
    print('CAUSAL_AGENT=PASS')
if __name__ == '__main__':
    main()
