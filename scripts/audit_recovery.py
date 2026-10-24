"""Record every remote branch, existing tags and file disposition for recovery."""
import json
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
def ancestor(a,b):
    return subprocess.run(['git','merge-base','--is-ancestor',a,b],cwd=ROOT).returncode == 0

recovery='origin/release/alpha9.4-publish-20261023'
p0='origin/feature/p0-combined-physical-execution'
main='origin/main'
branches=[]
for row in git('for-each-ref','--format=%(refname:short) %(objectname)','refs/remotes/origin').splitlines():
    name, sha = row.split()
    if name in ('origin/HEAD', 'origin'): continue
    covered = [ref for ref in (main,recovery,p0) if ancestor(sha,ref)]
    counts = git('rev-list','--left-right','--count',f'{recovery}...{sha}').split()
    branches.append(dict(branch=name.removeprefix('origin/'),sha=sha,
        covered_by=covered,recovery_only=int(counts[0]),branch_only=int(counts[1]),
        disposition='included_by_ancestry' if covered else 'preserved_historical_or_alternative_branch',
        differing_file_count=len(git('diff','--name-status',recovery,sha).splitlines()),
        diff_inventory_sha256=hashlib.sha256(git('diff','--name-status',recovery,sha).encode()).hexdigest()))
report=dict(main=git('rev-parse',main),recovery=git('rev-parse',recovery),p0=git('rev-parse',p0),
    branches=branches,tags=git('show-ref','--tags').splitlines(),
    main_file_differences=git('diff','--name-status',main,'HEAD').splitlines())
(ROOT/'docs/recovery_branch_audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'{len(branches)} branches; {sum(bool(b["covered_by"]) for b in branches)} covered by main/recovery/P0 ancestry; {len(report["tags"])} tag refs')
