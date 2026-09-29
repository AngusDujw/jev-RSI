"""Sign-preserving per-axis step proposal; no simulator or audit imports.

Reliability is a frozen empirical prior, NOT an online correctness certificate.
Zeroing small axes changes the vector direction and is reported explicitly.
"""
import math


class ReliabilityStep:
    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.response = [1.0] * 3
        self.trust = 1.0
        self.stalls = 0

    def propose(self, error, signs, uncertainty=None):
        if len(error) != 3 or len(signs) != 3:
            raise ValueError('Expected XYZ vectors')
        if not all(math.isfinite(float(x)) for x in error) or any(s not in (-1, 0, 1) for s in signs):
            raise ValueError('Invalid error or signs')
        b = list(uncertainty or [self.cfg['noise_floor_m']] * 3)
        rho = max(0., 2*self.cfg['direction_probability']-1)
        amplitude = [self.trust*rho*max(abs(e)-n, 0.)/k
                     for e, n, k in zip(error, b, self.response)]
        delta = [s*a for s, a in zip(signs, amplitude)]
        norm = math.sqrt(sum(x*x for x in delta))
        scale = min(1., self.cfg['max_step_m']/max(norm, 1e-15))
        delta = [x*scale for x in delta]
        return dict(delta_m=delta, axis_amplitudes_m=[abs(x) for x in delta],
                    norm_m=math.sqrt(sum(x*x for x in delta)), rho=rho,
                    uncertainty_m=b, response_gain=list(self.response), trust=self.trust,
                    suppressed_axes=[s != 0 and a == 0 for s, a in zip(signs, delta)],
                    direction_policy='nonnegative_per_axis_scaling_NO_sign_flip')

    def update(self, before, after, target, delta):
        # Same frozen target before/after; target jumps cannot fake progress.
        e0 = [t-x for t, x in zip(target, before)]
        e1 = [t-x for t, x in zip(target, after)]
        r0 = math.sqrt(sum(e*e for e in e0))
        r1 = math.sqrt(sum(e*e for e in e1))
        progress = r0-r1
        threshold = self.cfg['feedback_deadband_m']
        if progress < -threshold:
            self.trust = max(.125, self.trust*.5)
        elif progress > threshold:
            self.trust = min(1., self.trust*1.1)
        self.stalls = self.stalls+1 if abs(progress) <= threshold else 0
        for j, (x0, x1, u) in enumerate(zip(before, after, delta)):
            if abs(u) >= .001:
                observed = (x1-x0)/u
                if observed > 0 and math.isfinite(observed):
                    self.response[j] = min(1.5, max(.25, .8*self.response[j]+.2*observed))
        return dict(progress_m=progress, response_gain=list(self.response),
                    trust=self.trust, stalls=self.stalls)


def distance_step(error, signs, cap=.04, gain=.7):
    norm = math.sqrt(sum(s*s for s in signs))
    amplitude = min(cap, gain*math.sqrt(sum(e*e for e in error))) if norm else 0.
    return dict(delta_m=[amplitude*s/norm if norm else 0. for s in signs],
                norm_m=amplitude, direction_policy='scalar_original_sign_vector')
