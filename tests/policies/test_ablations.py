from pathlib import Path

import pytest

from auditgym.env import AuditEnv
from auditgym.generator.io import load_public
from auditgym.policies.ablations import FLAGS, VARIANTS, AblatedReconciler, reconcile_variant
from auditgym.policies.explorers import reconcile
from auditgym.runner.core import run_episode

ROOT = Path(__file__).resolve().parents[2]
EPISODES = sorted(p.parents[1] for p in (ROOT / "episodes").glob("*/*/public/manifest.json"))


@pytest.mark.parametrize("episode", EPISODES, ids=lambda p: p.name)
def test_no_flags_equals_reconciler(episode):
    public = load_public(episode)
    assert reconcile_variant(public) == reconcile(public)


def test_unknown_flag_rejected():
    with pytest.raises(ValueError):
        AblatedReconciler(["nope"])
    assert set().union(*VARIANTS.values()) == set(FLAGS)


def test_ablated_policy_runs_through_real_env():
    episode = ROOT / "episodes/train/train_09"
    with AuditEnv(mode="train") as env:
        rows, result = run_episode(env, AblatedReconciler(FLAGS), policy_name="ablation",
                                   reset_kwargs={"episode_dir": episode})
    assert rows[-1]["action"]["name"] == "submit"
    assert result["f1"] < 1.0
