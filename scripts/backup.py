"""Offline backup/restore. Stop studio first. Restore only into a new directory."""
import argparse, hashlib, json, shutil, sqlite3
from pathlib import Path

def backup(source, target):
    source=Path(source); target=Path(target)
    if target.exists(): raise ValueError('Backup target must not exist')
    target.mkdir(parents=True)
    with sqlite3.connect(source/'studio.db') as src, sqlite3.connect(target/'studio.db') as dst: src.backup(dst)
    if (source/'files').exists(): shutil.copytree(source/'files',target/'files')
    hashes={str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}
    (target/'manifest.json').write_text(json.dumps(hashes,indent=2))
    return hashes

def restore(source,target):
    source=Path(source); target=Path(target)
    if target.exists(): raise ValueError('Restore target must not exist')
    manifest=json.loads((source/'manifest.json').read_text())
    for name,digest in manifest.items():
        p=source/name
        if not p.resolve().is_relative_to(source.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=digest: raise ValueError('Backup checksum invalid')
    with sqlite3.connect(source/'studio.db') as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Database integrity failure')
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('manifest.json'))
    # A fresh local access key is generated on the next application launch.

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('mode',choices=['backup','restore']); p.add_argument('source');p.add_argument('target');a=p.parse_args()
    (backup if a.mode=='backup' else restore)(a.source,a.target)
    print(a.mode+' verified')
