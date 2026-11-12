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
    'backend': 'sha256:e713ff8b7a43a800549b94048efba403ee6e7314a28ae72a1cd7a73e33cf7731',
    'bot': 'sha256:9f2bad21e0f3884a7f31151accb3a06c5229991194afdc5685af22751fa1d47b',
}
images = []
with tempfile.TemporaryDirectory(prefix='dabarna-committed-build-') as tmp:
    root = Path(tmp)
    archive = run('git', 'archive', revision, 'backend/app', 'davarna-bot/bot')
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(root, filter='data')
    for service, parent in parents.items():
        parent_tag = f'dabarna-{service}:rc-850a6db'
        actual_parent = run('docker', 'image', 'inspect', '--format', '{{.Id}}', parent_tag, text=True).strip()
        if actual_parent != parent:
            raise RuntimeError('Candidate parent image identity changed')
        context = 'backend/app' if service == 'backend' else 'davarna-bot/bot'
        destination = '/app/app' if service == 'backend' else '/app/bot'
        dockerfile = root / ('Dockerfile.' + service)
        dockerfile.write_text(f'FROM {parent_tag}\nLABEL org.opencontainers.image.revision="{revision}"\nCOPY {context} {destination}\n')
        tag = f'dabarna-{service}:remaining-{revision[:7]}'
        subprocess.run(['docker', 'build', '--network', 'none', '--pull=false', '-f', str(dockerfile), '-t', tag, str(root)], check=True)
        expected = {str(path.relative_to(root / context)).replace('\\', '/'):hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (root / context).rglob('*') if path.is_file()}
        verify = 'import sys,json,hashlib,pathlib; expected=json.load(sys.stdin); root=pathlib.Path('+repr(destination)+'); bad=[p for p,h in expected.items() if hashlib.sha256((root/p).read_bytes()).hexdigest()!=h]; assert not bad,bad; print("VERIFIED",len(expected))'
        result = subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none', '--entrypoint', 'python', tag, '-c', verify],
                                input=json.dumps(expected), text=True, capture_output=True, check=True)
        image_id = run('docker', 'image', 'inspect', '--format', '{{.Id}}', tag, text=True).strip()
        images.append({'service':service, 'tag':tag, 'image_id':image_id, 'parent_image_id':parent,
                       'verified_source_files':len(expected), 'source_commit':revision})
        print(result.stdout.strip())
target = repo / 'dev/audit/remaining-20261111/candidate-images.json'
target.write_text(json.dumps({'deployed':False, 'images':images},indent=2)+'\n',encoding='utf8')
print(json.dumps({'result':'PASS','deployed':False,'images':images}))
