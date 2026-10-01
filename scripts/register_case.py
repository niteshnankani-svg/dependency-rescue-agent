"""Register operator-reviewed repository snapshots; API callers cannot register commands."""
import argparse
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rescue.config import Case,DATA,ROOT
from rescue.guards import digest_files,source_files


def safe_snapshot(root):
    for p in root.rglob('*'):
        if p.is_symlink() and not p.resolve().is_relative_to(root):
            raise ValueError('Snapshot contains an external symlink: '+str(p.relative_to(root)))
        if p.name=='.env' or p.name.startswith('.env.') or p.name in ['.npmrc','.pypirc']:
            raise ValueError('Remove credential/configuration files before registration: '+str(p.relative_to(root)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('definition',type=Path);parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--upgraded',type=Path,required=True)
    args=parser.parse_args();case=Case.model_validate_json(args.definition.read_text())
    baseline=args.baseline.resolve();upgraded=args.upgraded.resolve()
    for root in [baseline,upgraded]:safe_snapshot(root)
    if case.version(upgraded)!=case.target_version:
        raise ValueError('Installed upgraded version does not match case definition')
    if {str(p.relative_to(baseline)):p.read_bytes() for p in source_files(baseline,case.source_globs)}!={str(p.relative_to(upgraded)):p.read_bytes() for p in source_files(upgraded,case.source_globs)}:
        raise ValueError('Snapshots must differ only by the dependency upgrade, not pre-repaired source')
    def oracle(root):
        return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file() and not any(x in p.relative_to(root).parts for x in ['node_modules','.git']) and p.name not in ['package.json','package-lock.json'] and p not in source_files(root,case.source_globs)}
    if oracle(baseline)!=oracle(upgraded):
        raise ValueError('Tests and protected files must match between snapshots')
    registry=ROOT/'cases.json';rows=json.loads(registry.read_text())
    if case.id in {r['id'] for r in rows} or case.templates.exists():
        raise ValueError('Case already exists; register a new immutable version')
    case.templates.mkdir(parents=True)
    for phase,root in [('baseline',baseline),('upgraded',upgraded)]:
        shutil.copytree(root,case.templates/phase,symlinks=True,ignore=shutil.ignore_patterns('.git'))
    rows.append(case.model_dump())
    temp=registry.with_suffix('.tmp');temp.write_text(json.dumps(rows,indent=2)+'\n');temp.replace(registry)
    print('Registered '+case.id+'. Run scripts/evaluate.py '+case.id+' before relying on this case.')


if __name__=='__main__':main()
