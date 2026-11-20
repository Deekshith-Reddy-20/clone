import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "api"))

from app.config import get_settings
from app.services.telephony.exotel import exotel_configured, place_outbound_connect

get_settings.cache_clear()
s = get_settings()
print("configured", exotel_configured(s))
print("public", s.public_api_base_url)
base = s.public_api_base_url.rstrip("/")
cid = "00000000-0000-0000-0000-000000000099"
try:
    sid = place_outbound_connect(
        to_e164="+916300729913",
        voice_url=f"{base}/v1/webhooks/exotel/voice/{cid}",
        status_callback_url=f"{base}/v1/webhooks/exotel/status/{cid}",
        custom_field="probe",
        settings=s,
    )
    print("CallSid", sid)
    print("RINGING: pick up 6300729913 now")
except Exception as e:
    print("FAIL", e)
    sys.exit(1)