# 🐾 Pet-Med-Parser: AI-Powered Veterinary Schedule Manager

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-UI-FF4B4B)
![Gemini](https://img.shields.io/badge/Google%20Gemini-2.5%20Flash-orange)

![Demo](project_gif.gif)

---

## 📖 The Context (Why I built this)

As a Technical Support Engineer, I love using AI to solve real-world logistical problems. I built this tool to manage the highly complex medication schedules of my three senior dogs: **Arya** (16, heart issues), **Aécio** (13, liver cancer), and **Nino** (8, stomach problems).

Keeping track of multiple prescriptions was overwhelming for my mom. This application allows her to simply upload a photo of the vet's prescription. The AI extracts the medication, calculates the intervals, and generates an `.ics` file that automatically populates her Google Calendar.

---

## 🚀 Features

- **OCR & Vision AI:** Uses Google Gemini 2.5 Flash to read messy, handwritten veterinary prescriptions.
- **Elderly-Friendly UI:** A clean, intuitive web interface built with Streamlit so non-technical users (like my mom) can use it effortlessly.
- **Multi-Medication Support:** Extracts all numbered items from a single prescription in one pass.
- **Calendar Integration:** Automatically generates standard `.ics` files for 1-click import to Google/Apple Calendar.
- **🛡️ Human-in-the-Loop Safety:** Critical safety mechanism implemented via strict Prompt Engineering. If the handwriting is ambiguous, the AI is explicitly forbidden from guessing the dosage. It halts the process and presents editable fields for manual review, preventing dangerous medication errors.

---

## 🧠 Core Prompt Engineering Logic

To prevent LLM hallucinations, the API is called using a strict 4-tier framework:

1. **Persona:** `"You are a highly precise veterinary data extractor..."`
2. **Language Context:** The prompt explicitly states that all prescriptions are written in **Brazilian Portuguese (pt-BR)**, and maps common handwritten expressions to their numeric equivalents so the model interprets them correctly instead of flagging them as ambiguous:

   | Handwritten expression | Interpreted as |
   |---|---|
   | `"meio comprimido"` / `"(1/2)"` | 0.5 × pill strength |
   | `"1 e meio"` / `"1 + 1/2"` | 1.5 × pill strength |
   | `"uma vez ao dia"` | `interval_hours: 24` |
   | `"duas vezes ao dia"` / `"a cada 12h"` | `interval_hours: 12` |
   | `"três vezes ao dia"` / `"a cada 8h"` | `interval_hours: 8` |

3. **Few-Shot Examples:** Real-world pt-BR prescription examples with expected JSON output, including fractional dose calculations (e.g. `"Prediderm 20mg — meio comprimido"` → `dosage_mg: 10.0`).
4. **Negative Constraints:** `"If the handwriting is truly illegible, force needs_human_review: true and dosage_mg: null. Do NOT guess."`

When a prescription is flagged, the app enters a **Manual Review screen** where the user can correct any field before the calendar is generated. The patient name is always a fixed dropdown (`Arya`, `Nino`, `Aécio`) to prevent the AI from hallucinating unrecognised names. Dosage fields accept both `.` and `,` as decimal separators (e.g. `1.5` or `1,5`).

---

## 🗂️ Project Structure

```
Pet-Med-Parser/
├── app.py               # Streamlit web interface (main entry point)
├── process_recipe.py    # CLI version of the same logic (terminal use)
├── requirements.txt     # Python dependencies
├── .env.example         # API key placeholder
└── README.md
```

---

## 🛠️ Installation & Usage

**1. Clone the repository:**
```bash
git clone https://github.com/YourUsername/Pet-Med-Parser.git
cd Pet-Med-Parser
```

**2. Install dependencies:**
```bash
pip install -r requirements.txt
```

**3. Configure your API key:**
```bash
cp .env.example .env
# Open .env and paste your Gemini API key
# Get one free at: https://aistudio.google.com/app/apikey
```

**4. Launch the web app:**
```bash
streamlit run app.py
```

**5. Import the generated file into Google Calendar:**

`Google Calendar → Settings → Import & Export → Import → select agenda_<pet>.ics`

---

## 🖥️ Application Flow

```
Upload prescription photo
        │
        ▼
  Gemini Vision API
  (extracts all medications as JSON list)
        │
        ├─── All clear? ──────────────────────► Success screen
        │                                        Show medications + Download button
        │                                                  │
        └─── Ambiguous handwriting? ──────────► Manual Review screen              
                                                 Editable fields per medication
                                                 Patient locked to dropdown
                                                          │
                                                          ▼
                                                    Confirm → Download .ics
                                                          │
                                                          ▼
                                                   App resets to start
```

---

## 📦 Dependencies

| Library | Purpose |
|---|---|
| `google-generativeai` | Gemini API client for vision + text |
| `streamlit` | Web UI framework |
| `icalendar` | Generate `.ics` calendar files |
| `python-dotenv` | Load API key from `.env` |
| `pytz` | Timezone-aware calendar events |

---

*Built with love for Arya, Aécio, and Nino. 🐕*
