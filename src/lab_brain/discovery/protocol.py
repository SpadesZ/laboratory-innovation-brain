"""The pre-registered discovery protocol: every threshold and feature switch, frozen and hashed.

Nothing the loop decides is tuned after looking at a world: these constants are fixed before a run,
their digest is written into the benchmark manifest, and a test pins the defaults. The arms of the
offline benchmark are configurations of this one protocol, so "B2 beats B1" can only mean "these
switches change the outcome", never "B2 had a different statistic".

    alpha_refute          a hypothesis is REFUTED when its chi-square fit to the admitted
                          observations has an upper-tail p-value below this ...
    delta_chi2_refute     ... or when its chi-square exceeds the best live hypothesis's by more than
                          this (a likelihood-ratio test at the same alpha, one degree of freedom)
    z_anomaly             an observation is UNEXPLAINED when some entry's |standardised residual|
                          exceeds this under every live hypothesis's best fit
    z_reproduce           the replication test, when no declared hypothesis explains the replicate:
                          original and replicate agree (REPRODUCED) when every entry differs by at
                          most this many sqrt(2)*sigma, and are UNSTABLE otherwise
    distinguish_tau       two hypotheses are distinguishable when the full available protocol, each
                          experiment replicated `distinguish_replicates` times, separates their
                          predictions by at least this many standard units in the WORST case over
                          both amplitude ranges
    selection_tau         one run of an experiment is counted as fully separating a pair at this
                          standardised separation (partial credit below it)
    risky_separation      a test is one a hypothesis could have failed when, in the worst case over
                          amplitudes, it separates the hypothesis from the noise model or from
                          another registered hypothesis by at least this
    widen_batch           at most this many hypotheses are added by one widening
    max_widen_rounds      widening happens at most this many times
    max_noise_tests       at most this many replications are spent on noise attribution and
                          decisive replication together
    min_prospective_tests a hypothesis is SURVIVING only after passing prospective tests on this
                          many distinct experiments it could have failed (severity)
    decisive_replication  before a claim, the observation a rival's refutation rests on alone is
                          replicated once (within the noise-test allowance and the budget)
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from lab_brain.discovery.model import stable_digest


@dataclass(frozen=True)
class DiscoveryProtocol:
    protocol_id: str = "lab-brain/discovery-loop-offline"
    version: str = "0.1.0"
    alpha_refute: float = 1e-3
    #: The comparative half of the refutation rule: a hypothesis whose chi-square exceeds the best
    #: live hypothesis's by more than this (the 0.999 quantile of chi-square with one degree of
    #: freedom, so the same alpha as a likelihood-ratio test) is refuted.
    delta_chi2_refute: float = 10.828
    z_anomaly: float = 4.0
    z_reproduce: float = 3.0
    distinguish_tau: float = 5.0
    distinguish_replicates: int = 4
    selection_tau: float = 4.0
    risky_separation: float = 3.0
    widen_batch: int = 8
    max_widen_rounds: int = 2
    max_noise_tests: int = 2
    #: A hypothesis is SURVIVING only after passing prospective tests on this many DISTINCT
    #: experiments it could have failed (severity). The existing loop's shape is one.
    min_prospective_tests: int = 2
    #: Before a claim, replicate the observation on which a rival's refutation rests alone.
    decisive_replication: bool = True
    #: Before a claim, register every declared hypothesis of no greater complexity than the
    #: candidate class that the admitted data do not refute and that is distinguishable from
    #: everything held, and discriminate it too: a claim stands against all declared rivals.
    rival_closure: bool = True
    #: Prior weight given to a hypothesis the catalog's prior does not cover (variants, extended
    #: classes, compositions) once data motivated it. Used for selection weights only.
    widened_prior_floor: float = 0.02
    #: Selection weight of the noise-model hypothesis (no mechanism at all).
    null_prior: float = 0.05
    # Feature switches. B1 ("existing LIB style") turns every one of these off.
    anomalies: bool = True
    noise_test: bool = True
    expansion: bool = True
    measurement_chain_review: bool = True
    #: Record reframings (and stop with typed STOP_INSUFFICIENT / CHANGE_OBSERVABLE records).
    reframing: bool = True
    closure: bool = True
    #: Never refute a hypothesis while an indistinguishable one survives (no resolution by fiat).
    indistinguishable_guard: bool = True
    #: Report a surviving class of indistinguishable members; when False, only a single surviving
    #: hypothesis is a claim (the existing loop's "exactly one SUPPORTED class" shape).
    report_classes: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.alpha_refute < 1:
            raise ValueError("alpha_refute is a probability")
        if min(self.z_anomaly, self.z_reproduce, self.distinguish_tau, self.selection_tau) <= 0:
            raise ValueError("thresholds are positive")
        if self.distinguish_replicates < 1 or self.widen_batch < 1:
            raise ValueError("counts are positive")

    @property
    def digest(self) -> str:
        return stable_digest(self)


#: B2: the existing loop plus discovery.
DISCOVERY = DiscoveryProtocol()

#: B1: a fixed initial hypothesis set with discrimination-per-cost verification -- no anomaly
#: records, no noise test, no expansion, no reframing, no closure, no class reporting.
EXISTING_LIB_STYLE = replace(
    DISCOVERY,
    anomalies=False,
    noise_test=False,
    expansion=False,
    measurement_chain_review=False,
    reframing=False,
    min_prospective_tests=1,
    decisive_replication=False,
    rival_closure=False,
    closure=False,
    indistinguishable_guard=False,
    report_classes=False,
)


__all__ = ["DISCOVERY", "EXISTING_LIB_STYLE", "DiscoveryProtocol"]
