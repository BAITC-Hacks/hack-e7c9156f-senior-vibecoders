from ai.report import usable
from ai.schemas import CriticVerdict, Evidence, Finding, Review

EV = Evidence(doc_id="a1", doc_name="x", side="after", clause_id="3.4", quote="q", verified=True)


def finding(critic=None, review=None, verified=True):
    return Finding(id="f", type="duplication", severity="medium", title="t", description="d",
                   evidence=[EV.model_copy(update={"verified": verified})],
                   critic=CriticVerdict(verdict=critic, argument="a") if critic else None,
                   review=Review(status=review, reviewed_at="2026-09-23T12:00:00Z") if review else None)


def test_critic_refuted_excluded():
    assert usable(finding(critic="upheld"))
    assert usable(finding(critic="uncertain"))
    assert not usable(finding(critic="refuted"))


def test_human_review_overrides_critic():
    assert usable(finding(critic="refuted", review="accepted"))
    assert not usable(finding(critic="upheld", review="rejected"))


def test_unverified_never_used():
    assert not usable(finding(review="accepted", verified=False))
