"""Build and verify local candidates from a committed tree; never deploy or push images."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

repo = Path(__file__).resolve().parents[2]
def run(*args, **kwargs):
    return subprocess.check_output(args, cwd=repo, **kwargs)

revision = run('git', 'rev-parse', 'HEAD', text=True).strip()
parents = {
    'backend': 'sha256:64556bf2edb7babdb5b7885825ec325d3905c4141931e31f4a94fb245e31812b',
    'bot': 'sha256:d947a81ae03c8d79fa6bca865fd65358886e28a6458f8a9993cc5aadcd97f96c',
}
images = []
with tempfile.TemporaryDirectory(prefix='dabarna-committed-build-') as tmp:
    root = Path(tmp)
    archive = run('git', 'archive', revision, 'backend/app', 'backend/alembic', 'backend/alembic.ini', 'davarna-bot/bot')
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(root, filter='data')
    for service, parent in parents.items():
        parent_tag = f'docker.io/library/dabarna-{service}:remaining-4f1b0fd'
        actual_parent = run('docker', 'image', 'inspect', '--format', '{{.Id}}', parent_tag, text=True).strip()
        if actual_parent != parent:
            raise RuntimeError('Candidate parent image identity changed')
        context = 'backend/app' if service == 'backend' else 'davarna-bot/bot'
        destination = '/app/app' if service == 'backend' else '/app/bot'
        dockerfile = root / ('Dockerfile.' + service)
        migration_copy = 'COPY backend/alembic /app/alembic\nCOPY backend/alembic.ini /app/alembic.ini\n' if service == 'backend' else ''
        dockerfile.write_text(f'FROM {parent_tag}\nLABEL org.opencontainers.image.revision="{revision}"\nCOPY {context} {destination}\n'+migration_copy)
        tag = f'docker.io/library/dabarna-{service}:final-{revision[:7]}'
        subprocess.run(['docker', 'build', '--network', 'none', '--pull=false', '-f', str(dockerfile), '-t', tag, str(root)], check=True)
        expected = {destination+'/'+str(path.relative_to(root / context)).replace('\\', '/'):hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (root / context).rglob('*') if path.is_file()}
        if service == 'backend':
            for path in (root/'backend/alembic').rglob('*'):
                if path.is_file():
                    expected['/app/alembic/'+path.relative_to(root/'backend/alembic').as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
            expected['/app/alembic.ini']=hashlib.sha256((root/'backend/alembic.ini').read_bytes()).hexdigest()
        verify = 'import sys,json,hashlib,pathlib; expected=json.load(sys.stdin); bad=[p for p,h in expected.items() if hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()!=h]; assert not bad,bad; print("VERIFIED",len(expected))'
        result = subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none', '--entrypoint', 'python', tag, '-c', verify],
                                input=json.dumps(expected), text=True, capture_output=True, check=True)
        image_id = run('docker', 'image', 'inspect', '--format', '{{.Id}}', tag, text=True).strip()
        images.append({'service':service, 'tag':tag, 'image_id':image_id, 'parent_image_id':parent,
                       'verified_source_files':len(expected), 'source_commit':revision})
        print(result.stdout.strip())
target = repo / 'dev/audit/final-integration-20261113/candidate-images.json'
target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps({'deployed':False, 'images':images},indent=2)+'\n',encoding='utf8')
print(json.dumps({'result':'PASS','deployed':False,'images':images}))
