"""
WhatsApp echo webhook via the TWILIO WhatsApp Sandbox, hosted on Modal (CPU only).

What it proves:
  - Twilio can reach your webhook and the request is genuine (signature check)
  - text, voice notes and location pins arrive
  - voice notes can be downloaded (needed for ASR later)
  - you can reply; a location pin gets a REAL postcode back from the Postcode API

One-time secret (values from the Twilio Console):
  modal secret create twilio \
      TWILIO_ACCOUNT_SID=ACxxxxxxxx \
      TWILIO_AUTH_TOKEN=xxxxxxxx \
      TWILIO_WHATSAPP_FROM="whatsapp:+14155238886" \
      POSTCODE_API_KEY=nipost_test_xxx

Deploy:  modal deploy twilio_echo.py
In Twilio sandbox settings, "When a message comes in" = <printed URL>/twilio  (method POST)
Logs:    modal app logs naic-twilio-echo
"""
import os

import modal

app = modal.App("naic-twilio-echo")
image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "fastapi[standard]", "httpx", "twilio"
)

POSTCODE_API = "https://api.postcode.gov.ng"
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


@app.function(image=image, secrets=[modal.Secret.from_name("twilio")], scaledown_window=300)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    import httpx
    from fastapi import FastAPI, HTTPException, Request, Response
    from twilio.request_validator import RequestValidator
    from twilio.twiml.messaging_response import MessagingResponse

    SID = os.environ["TWILIO_ACCOUNT_SID"]
    TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
    PC_KEY = os.environ.get("POSTCODE_API_KEY", "")

    validator = RequestValidator(TOKEN)
    api = FastAPI()
    seen: set[str] = set()   # Twilio may retry; handle each message once

    @api.get("/")
    def health():
        return {"ok": True}

    # ---- incoming messages -------------------------------------------------------
    @api.post("/twilio")
    async def receive(request: Request):
        form = dict(await request.form())
        # Twilio signs the exact public https URL it called
        url = str(request.url).replace("http://", "https://", 1)
        if not validator.validate(url, form, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(status_code=403, detail="bad signature")

        sid = form.get("MessageSid", "")
        if sid in seen:                      # Twilio retry: don't answer twice
            return Response(content=EMPTY_TWIML, media_type="application/xml")
        seen.add(sid)

        reply = await handle(form)
        # Reply inside Twilio's response (TwiML). Free text is allowed here, no template needed.
        twiml = MessagingResponse()
        twiml.message(reply)
        print("REPLY", reply[:200])
        return Response(content=str(twiml), media_type="application/xml")

    # ---- helpers -----------------------------------------------------------------
    async def download_media(url: str) -> bytes:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
            r = await c.get(url, auth=(SID, TOKEN))   # Twilio media needs basic auth
            r.raise_for_status()
            return r.content

    async def reverse_postcode(lat: str, lng: str) -> str:
        if not PC_KEY:
            return "(no POSTCODE_API_KEY set)"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{POSTCODE_API}/v1/search/reverse",
                            params={"lat": lat, "lng": lng, "max_distance_m": 250},
                            headers={"X-API-Key": PC_KEY})
        d = r.json().get("data", {})
        if d.get("found"):
            u = d["unit"]
            return f"{u['postcode']} ({u['confidence']} confidence, {u['distance_m']} m away)"
        return f"No postcode found within {d.get('radius_m', 250)} m"

    # ---- the echo logic ------------------------------------------------------------
    async def handle(form: dict) -> str:
        num_media = int(form.get("NumMedia", "0") or 0)
        print("IN", {k: v for k, v in form.items() if k not in ("From", "To", "WaId", "ProfileName")})

        try:
            if form.get("Latitude") and form.get("Longitude"):
                lat, lng = form["Latitude"], form["Longitude"]
                postcode = await reverse_postcode(lat, lng)
                reply = f"Got your location: {lat}, {lng}\nPostcode: {postcode}"
            elif num_media > 0:
                ctype = form.get("MediaContentType0", "")
                audio = await download_media(form["MediaUrl0"])
                reply = f"Got your {'voice note' if ctype.startswith('audio') else 'file'}: {len(audio):,} bytes ({ctype})."
            elif form.get("Body"):
                reply = f"Echo: {form['Body']}"
            else:
                reply = "Received a message I don't handle yet."
        except Exception as e:
            print("ERROR", repr(e))
            reply = "Sorry, something went wrong. Please try again."

        return reply

    return api