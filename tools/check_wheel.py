"""Install a wheel into a disposable directory and exercise it outside the repo."""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CODE = """
import json
from pathlib import Path
from importlib.resources import files
import auditgym
from auditgym.generator import generate
from auditgym.grader import Grader
from auditgym.policies import Oracle, Reconciler
from auditgym.env import AuditEnv
from auditgym.runner import run_episode
assert Path(auditgym.__file__).resolve().is_relative_to(Path('installed').resolve())
schemas = [p for p in files('auditgym.schemas').iterdir() if p.name.endswith('.schema.json')]
assert len(schemas) == 10
for schema in schemas:
    json.loads(schema.read_text())
episode = generate(7, {})
answer = Oracle(episode.truth).act({'manifest': episode.public['manifest']})['args']['findings']
assert Grader().score(answer, public=episode.public, truth=episode.truth).reward == 1
with AuditEnv() as env:
    rows, result = run_episode(env, Reconciler(), policy_name='Reconciler',
                              reset_kwargs={'seed': 7})
    assert result['f1'] == 1 and result['scored']
print(json.dumps({'status': 'passed', 'env_version': auditgym.ENV_VERSION,
                  'packaged_schemas': len(schemas), 'oracle_reward': 1, 'reconciler_f1': result['f1']}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if not wheel.is_file():
        parser.error("Wheel does not exist")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        installed = root / "installed"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--target",
                        str(installed), str(wheel)], check=True)
        env = dict(os.environ, PYTHONPATH=str(installed) + os.pathsep + os.environ.get("PYTHONPATH", ""),
                   PYTHONDONTWRITEBYTECODE="1")
        subprocess.run([sys.executable, "-B", "-c", CODE], cwd=root, env=env, check=True)


if __name__ == "__main__":
    main()
