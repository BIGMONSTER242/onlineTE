"""Package only validated experiment outputs, never a whole checkout or home directory."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path
try:
    from .summarize import load_validate, safe_file, summarize
except ImportError:
    from summarize import load_validate, safe_file, summarize


def pack(run_dir):
    root, manifest, _, rows = load_validate(run_dir)
    summarize(root)
    names = {'manifest.json','results.csv','summary.md','summary.json'}
    names.update(manifest['inputs'])
    names.update(r['log_path'] for r in rows if r.get('log_path'))
    names.update(p.name for p in root.glob('gap_*.png'))
    if (root/'attempts.csv').exists(): names.add('attempts.csv')
    for directory in ('logs','baseline'):
        for path in (root/directory).rglob('*'):
            if path.is_symlink():
                raise ValueError(f'Symlink in output tree: {path.relative_to(root)}')
            if path.is_file() and path.suffix in {'.json','.log','.txt','.npy','.npz'}:
                names.add(str(path.relative_to(root)))
    # White-list only files explicitly referenced by the manifest/results plus summary artifacts.
    files = [(name,safe_file(root,name)) for name in sorted(names)]
    denied = {'.env','.git','credentials','gurobi.lic','license.lic'}
    for name,_ in files:
        if any(part.lower() in denied or part.lower().endswith(('.pem','.key','.lic')) for part in Path(name).parts):
            raise ValueError(f'Refusing potentially secret file: {name}')
    target = root.parent/(root.name+'-results.tar.gz')
    if target.is_symlink():
        raise ValueError('Archive destination is a symlink')
    checksums = {name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in files}
    with tarfile.open(target,'w:gz') as tf:
        for name,path in files:
            tf.add(path,arcname=f'{root.name}/{name}',recursive=False)
        content=(json.dumps(checksums,indent=2)+'\n').encode()
        info=tarfile.TarInfo(f'{root.name}/checksums.json'); info.size=len(content)
        tf.addfile(info,io.BytesIO(content))
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--run-dir',required=True)
    args=parser.parse_args()
    try:
        print(pack(args.run_dir))
    except (ValueError,KeyError,OSError,ImportError) as exc:
        parser.exit(1,f'Pack failed: {exc}\n')

if __name__=='__main__':
    main()
