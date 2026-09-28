"""Check that a long note keeps its duration while nearby attacks move lanes."""
import importlib.util
import sys
from pathlib import Path


sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    'drum_charts', Path(__file__).with_name('build-drum-charts.py'))
drum_charts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drum_charts)

events = [
    {'t': .5, 'active': {'kick': 1}, 'voices': {'kick': 1, 'hat': 1}},
    {'t': .7, 'active': {'kick': 1}, 'voices': {'kick': 1}},
    {'t': .9, 'active': {'kick': 1}, 'voices': {'kick': 1}},
    {'t': 1.1, 'active': {'snare': 1}, 'voices': {'snare': 1}},
]
notes = drum_charts.chart_notes(events, 'normal', 5, 120)
holds = [note for note in notes if note['hold']]
assert len(notes) == 5 and len(holds) == 1
hold = holds[0]
assert (hold['t'], hold['lane'], hold['hold']) == (.5, 2, 1.0)
assert sorted(note['t'] for note in notes) == [.5, .5, .7, .9, 1.1]
for note in notes:
    if note is hold:
        continue
    assert note['lane'] != 2
    assert note['lane'] == 3 or note['lane'] > 3

head_collision = [
    {'t': .1, 'active': {'kick': 1}, 'voices': {'kick': 1}},
    {'t': .3, 'active': {'kick': 1}, 'voices': {'kick': 1}},
    {'t': .5, 'active': {'kick': 1}, 'voices': {'kick': 1, 'hat': 1}},
]
notes = drum_charts.chart_notes(head_collision, 'normal', 5, 120)
head = [note for note in notes if note['t'] == .5]
assert len(head) == 2, 'a tap on the intended hold lane must not cancel the hold'
assert sorted(note['hold'] for note in head) == [0, 1.0]
assert next(note['lane'] for note in head if not note['hold']) >= 3

print('PASS: long-note count and length retained; nearby drum hits moved to free fingers')
