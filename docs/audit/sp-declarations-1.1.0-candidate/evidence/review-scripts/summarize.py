"""Pair the 1.0.0 and 1.1.0 episodes of each (variant, strategy) into one table row."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ABBR = {
    "extraction_consistency": "ext", "inspect_contact_connectivity": "conn",
    "mesh_sensitivity": "mesh", "charge_dc_sweep": "dc",
}
rows = {}
for name in ("results.jsonl", "results2.jsonl"):
    for line in (HERE / name).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        rows[(r["variant"], r["strategy"], r["version"])] = r  # results2 overrides duplicates

def cell(r):
    if "error" in r:
        return "ERROR " + r["error"]
    out = r["stop"]
    if r["confirmed"]:
        out += f" **{r['confirmed']}**"
    if r["pending"]:
        out += f" -> {r['pending'].removeprefix('cap:sp.')}"
    checks = "+".join(
        f"{ABBR.get(o.split(':')[0], o.split(':')[0])}:{o.split(':')[1].split('@')[0]}"
        for o in r["outcomes"]
    )
    return f"{out} [{checks}]"

keys = sorted({(v, s) for v, s, _ in rows})
for v, s in keys:
    a, b = rows.get((v, s, "1.0.0")), rows.get((v, s, "1.1.0"))
    dev = {k: val for k, val in (a or b)["device"].items() if k != "contacts"}
    if "contacts" in (a or b)["device"]:
        dev["contacts"] = ",".join(
            f"{c['contact_id']}:{'via' if c['via_to_metal'] else 'NOVIA'}/{c['overlap_nm']}nm"
            for c in (a or b)["device"]["contacts"]
        )
    un = (a or b).get("unavailable") or []
    print(f"| {v} | {s} | {json.dumps(dev)} {('unavail=' + ','.join(u.removeprefix('cap:sp.') for u in un)) if un else ''} | {cell(a)} | {cell(b)} |")
