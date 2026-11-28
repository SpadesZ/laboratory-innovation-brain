# Development / audit helper for the v1.5 held-out resume (run with PYTHONPATH=src).
"""Re-run a sample of held-out world tasks that finished before the interruption, from nothing, in
boundary mode, and compare every record with the checkpointed one (equality of all fields and of
the JSON row text)."""
import sys, importlib.util, pickle, json
sys.path.insert(0,'/home/user/wt/disc15/src')
spec=importlib.util.spec_from_file_location('s15','/home/user/wt/disc15/scripts/discovery_safety_v15_eval.py')
s=importlib.util.module_from_spec(spec); spec.loader.exec_module(s)
from pathlib import Path
snap=Path(sys.argv[1]); idx=[int(x) for x in sys.argv[2].split(',')]
H=3034793000; P=s.PLAN; arms=s.ev.ARM_IDS
s._init('boundary',arms)
for i in idx:
    task=(H,P.held_out_per_class,i,True,P.budgets)
    k=s._task_key(s._held_out_task,(arms,task))
    old=pickle.loads((snap/f'{k}.pickle').read_bytes())
    new=s._held_out_task(task)
    same=old==new and s._dump_rows(s.ev.records_as_json(old))==s._dump_rows(s.ev.records_as_json(new))
    print(f'held_out index {i} {new[0].world_id}: {len(new)} runs, identical={same}',flush=True)
