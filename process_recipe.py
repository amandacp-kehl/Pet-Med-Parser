"""
process_recipe.py
-----------------
Reads a vet prescription image, extracts the medication schedule using
the Gemini 1.5 Pro API, and outputs a schedule.ics calendar file.

Usage:
    python process_recipe.py <path_to_prescription_image>

Example:
    python process_recipe.py prescription.jpg
"""

import sys
import os
import json
from datetime import datetime, timedelta

# --- Dependency imports ---
# Load environment variables from the .env file (our API key lives there)
from dotenv import load_dotenv

# Official Google Gemini SDK
import google.generativeai as genai

# Library to build .ics calendar files
from icalendar import Calendar, Event
import pytz  # timezone support for calendar events


# ─────────────────────────────────────────────
# STEP 1: LOAD CONFIGURATION
# ─────────────────────────────────────────────

# This reads the GEMINI_API_KEY from the .env file so we never
# hardcode a secret directly in the script.
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("❌ Error: GEMINI_API_KEY not found.")
    print("   Make sure you copied .env.example to .env and filled in your key.")
    sys.exit(1)

genai.configure(api_key=API_KEY)


# ─────────────────────────────────────────────
# STEP 2: VALIDATE THE INPUT FILE
# ─────────────────────────────────────────────

# The script expects exactly one argument: the path to the prescription image.
if len(sys.argv) != 2:
    print("Usage: python process_recipe.py <path_to_image>")
    print("Example: python process_recipe.py prescription.jpg")
    sys.exit(1)

image_path = sys.argv[1]

if not os.path.exists(image_path):
    print(f"❌ Error: File not found: {image_path}")
    sys.exit(1)


# ─────────────────────────────────────────────
# STEP 3: BUILD THE PROMPT
# ─────────────────────────────────────────────

# This is the core of the project. The prompt uses three techniques:
#
#   1. PERSONA — tells the model exactly what role to play
#   2. FEW-SHOT EXAMPLE — shows it the exact input/output format we expect
#   3. STRICT CONSTRAINTS — prevents the model from guessing when unsure
#
# The "needs_human_review" flag is our safety valve. If the AI is not
# 100% confident about a dosage, it MUST set this to true and stop.

PROMPT = """
You are a highly precise veterinary data extractor. Your only job is to read
handwritten or printed prescription images and extract medication instructions
into a strict JSON format.

--- FEW-SHOT EXAMPLE ---
Input image content: "Give Arya half a pill of Vetmedin 5mg every 12 hours."
Expected output:
{
  "patient": "Arya",
  "medication": "Vetmedin",
  "dosage_mg": 2.5,
  "interval_hours": 12,
  "needs_human_review": false
}

--- STRICT CONSTRAINTS ---
1. You MUST output ONLY valid JSON. No extra text, no markdown, no explanation.
2. If the handwriting is ambiguous, illegible, or you are unsure about the
   dosage value or unit, you MUST set:
   - "needs_human_review": true
   - "dosage_mg": null
   DO NOT guess. A wrong dosage can harm a sick animal.
3. "interval_hours" must be a number (e.g., 12 for every 12 hours, 24 for once daily).
4. "patient" must be the animal's name exactly as written.

Now extract the medication schedule from the attached prescription image.
"""


# ─────────────────────────────────────────────
# STEP 4: CALL THE GEMINI API
# ─────────────────────────────────────────────

print(f"📄 Reading prescription: {image_path}")
print("🤖 Sending to Gemini 1.5 Pro for extraction...")

# Load the image from disk and upload it to Gemini as a file part.
# Gemini's multimodal API accepts both text and images in the same request.
image_data = genai.upload_file(path=image_path)

# Initialize the model — we use 1.5 Pro for its strong vision capabilities.
model = genai.GenerativeModel(model_name="gemini-2.5-flash")

# Send the prompt + image together. The model sees both simultaneously.
response = model.generate_content([PROMPT, image_data])

# Pull the raw text out of the response object.
raw_text = response.text.strip()


# ─────────────────────────────────────────────
# STEP 5: PARSE THE JSON RESPONSE
# ─────────────────────────────────────────────

# The model sometimes wraps the JSON in markdown code fences (```json ... ```)
# even when told not to. We strip those out before parsing so json.loads()
# always receives clean JSON regardless of model behaviour.
if raw_text.startswith("```"):
    raw_text = raw_text.split("\n", 1)[1]       # drop the opening ```json line
    raw_text = raw_text.rsplit("```", 1)[0]     # drop the closing ``` line
    raw_text = raw_text.strip()

try:
    data = json.loads(raw_text)
except json.JSONDecodeError:
    print("❌ Error: Gemini did not return valid JSON. Raw response was:")
    print(raw_text)
    sys.exit(1)


# ─────────────────────────────────────────────
# STEP 6: HUMAN-IN-THE-LOOP CHECK
# ─────────────────────────────────────────────

# This is the safety gate. If the AI flagged anything as ambiguous,
# we stop completely and refuse to create a calendar with bad data.
if data.get("needs_human_review") is True:
    print()
    print("=" * 60)
    print("🚨 WARNING: Handwriting ambiguous.")
    print("   Please review the prescription manually.")
    print("   Script stopped. No calendar file was created.")
    print("=" * 60)
    print()
    sys.exit(0)  # Exit cleanly (not an error, just a safe stop)


# ─────────────────────────────────────────────
# STEP 7: VALIDATE EXTRACTED DATA
# ─────────────────────────────────────────────

# Before building the calendar, make sure the required fields are present
# and have the right types. Better to catch this here than create a broken
# .ics file that silently imports wrong events.
required_fields = ["patient", "medication", "dosage_mg", "interval_hours"]
for field in required_fields:
    if field not in data or data[field] is None:
        print(f"❌ Error: Missing or null required field: '{field}'")
        print("   Extracted data was:", data)
        sys.exit(1)

patient = data["patient"]
medication = data["medication"]
dosage_mg = float(data["dosage_mg"])
interval_hours = int(data["interval_hours"])


# ─────────────────────────────────────────────
# STEP 8: BUILD THE .ICS CALENDAR FILE
# ─────────────────────────────────────────────

# We generate 7 days of events (one full week) so the schedule
# is visible in Google Calendar right away without being overwhelming.
DAYS_TO_SCHEDULE = 7
TIMEZONE = pytz.timezone("America/Sao_Paulo")  # Adjust to your local timezone

# Create a new calendar object.
cal = Calendar()
cal.add("prodid", "-//Pet-Med-Parser//pet-med-parser//EN")
cal.add("version", "2.0")
cal.add("calname", f"Medications — {patient}")

# Start scheduling from the next full hour to keep events clean-looking.
now = datetime.now(TIMEZONE)
start_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

# Calculate total number of doses: doses_per_day × 7 days
doses_per_day = 24 // interval_hours
total_doses = doses_per_day * DAYS_TO_SCHEDULE

print(f"📅 Scheduling {total_doses} doses over {DAYS_TO_SCHEDULE} days...")

for i in range(total_doses):
    # Each event starts at the calculated dose time and lasts 15 minutes.
    event_start = start_time + timedelta(hours=interval_hours * i)
    event_end = event_start + timedelta(minutes=15)

    event = Event()
    event.add("summary", f"💊 {patient} — {medication} {dosage_mg}mg")
    event.add("dtstart", event_start)
    event.add("dtend", event_end)
    event.add(
        "description",
        f"Give {patient} {dosage_mg}mg of {medication}.\n"
        f"Generated by Pet-Med-Parser on {now.strftime('%Y-%m-%d')}.",
    )

    cal.add_component(event)

# Write the completed calendar to disk.
output_file = "schedule.ics"
with open(output_file, "wb") as f:
    f.write(cal.to_ical())


# ─────────────────────────────────────────────
# STEP 9: DONE — REPORT SUCCESS
# ─────────────────────────────────────────────

print()
print("✅ Success! .ics file generated — ready to be imported to Google Calendar.")
print(f"   Patient   : {patient}")
print(f"   Medication: {medication} — {dosage_mg}mg every {interval_hours}h")
print(f"   File      : {os.path.abspath(output_file)}")
print()
print("   To import: Google Calendar → Settings → Import & Export → Import")
