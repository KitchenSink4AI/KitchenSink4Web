import os
import pytest
from kitchensink4web.policy import consent, readonly

pytestmark = pytest.mark.browser


def test_zz_probe_consent_state():
    print("\nSCOPE:", consent.scope(), "SOURCE:", consent.source()
          if hasattr(consent, "source") else "?")
    print("ENVS:", {k: os.environ.get(k) for k in
                    ("KS4WEB_CONSENT", "KS4WEB_PREAUTH",
                     "KS4WEB_SENSITIVE_ORIGINS", "KS4WEB_REMEMBER")})
    print("GRADE:", readonly.grade())
    print("GRANTS:", getattr(consent, "_GRANTS", getattr(consent, "_grants", "?")))
    d = consent.decide("form_submit", url="http://127.0.0.1:9/x", desc=None)
    print("DECIDE:", d.outcome, d.clears, d.reason)
