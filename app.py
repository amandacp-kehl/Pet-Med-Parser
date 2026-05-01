"""
app.py
------
Streamlit web interface for Pet-Med-Parser.
Wraps the Gemini API logic in a friendly UI designed for non-technical users.

Run with:
    streamlit run app.py
"""

import os
import json
import tempfile
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from datetime import datetime, timedelta

import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai
from icalendar import Calendar, Event
import pytz


# ─────────────────────────────────────────────
# STEP 1: PAGE CONFIGURATION
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Receitas Pet da Mamãe",
    page_icon="🐾",
    layout="centered",
)


# ─────────────────────────────────────────────
# STEP 2: LOAD API KEY
# ─────────────────────────────────────────────

load_dotenv()
API_KEY        = os.getenv("GEMINI_API_KEY")
GMAIL_SENDER   = os.getenv("GMAIL_SENDER")
GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

if not API_KEY:
    st.error("❌ GEMINI_API_KEY não encontrada. Verifique o arquivo .env.")
    st.stop()

genai.configure(api_key=API_KEY)


# ─────────────────────────────────────────────
# STEP 3: THE GEMINI PROMPT
# ─────────────────────────────────────────────

PROMPT = """
You are a highly precise veterinary data extractor. Your only job is to read
handwritten or printed prescription images and extract ALL medication instructions
into a strict JSON format.

--- LANGUAGE NOTE ---
All prescriptions are written in Brazilian Portuguese (pt-BR). Common terms you will see:
- "meio comprimido" or "(1/2)" = half a tablet → dosage_mg = half the pill strength (e.g. 20mg pill → 10mg)
- "1 e meio" or "1 + 1/2" or "1,5 comprimido" = 1.5 tablets → multiply pill strength by 1.5
- "uma vez ao dia" = once a day → interval_hours = 24
- "a cada 12h" or "duas vezes ao dia" = every 12 hours → interval_hours = 12
- "a cada 8h" or "três vezes ao dia" = every 8 hours → interval_hours = 8
- "comprimido", "cápsula", "cp", "cps" = tablet/capsule

--- FEW-SHOT EXAMPLES ---
Input: "1. Prediderm 20mg — dar meio comprimido (1/2), a cada 24h"
Output item: { "medication": "Prediderm", "dosage_mg": 10.0, "interval_hours": 24, "needs_human_review": false }

Input: "2. Condroplexo 100 — dar 1 e meio (1/2), uma vez ao dia"
Output item: { "medication": "Condroplexo", "dosage_mg": 150.0, "interval_hours": 24, "needs_human_review": false }

Input: "3. Vetmedin 5mg — dar meio comprimido a cada 12h"
Output item: { "medication": "Vetmedin", "dosage_mg": 2.5, "interval_hours": 12, "needs_human_review": false }

Full expected output format:
[
  {
    "patient": "Arya",
    "medication": "Prediderm",
    "dosage_mg": 10.0,
    "interval_hours": 24,
    "needs_human_review": false
  },
  {
    "patient": "Arya",
    "medication": "Condroplexo",
    "dosage_mg": 150.0,
    "interval_hours": 24,
    "needs_human_review": false
  }
]

--- STRICT CONSTRAINTS ---
1. You MUST output ONLY a valid JSON array (list). Even if there is only one
   medication, wrap it in a list: [{ ... }].
2. No extra text, no markdown, no explanation outside the JSON.
3. Extract EVERY numbered medication item you find in the image. Do NOT skip any.
4. Always calculate the actual dosage in mg based on the pill strength × quantity.
   Example: "meio comprimido de 20mg" → dosage_mg = 10.0
   Example: "1 e meio comprimido de 100mg" → dosage_mg = 150.0
5. If the handwriting of a specific item is truly illegible and you cannot determine
   the dosage or interval even after careful reading, set for THAT item only:
   - "needs_human_review": true
   - "dosage_mg": null
   DO NOT guess. A wrong dosage can harm a sick animal.
6. "interval_hours" must be a number (e.g., 12 for every 12 hours, 24 for once daily).
7. "patient" must be the animal's name exactly as written in the "Paciente" field.

Now extract ALL medication items from the attached prescription image.
"""


# ─────────────────────────────────────────────
# STEP 4: HELPER — CALL GEMINI API
# ─────────────────────────────────────────────

def call_gemini(image_bytes: bytes, mime_type: str) -> list:
    suffix = ".jpg" if "jpeg" in mime_type else ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    try:
        uploaded_file = genai.upload_file(path=tmp_path)
        model = genai.GenerativeModel(model_name="gemini-2.5-flash")
        response = model.generate_content([PROMPT, uploaded_file])
    finally:
        os.unlink(tmp_path)

    raw_text = response.text.strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        raw_text = raw_text.rsplit("```", 1)[0].strip()

    result = json.loads(raw_text)
    if isinstance(result, dict):
        result = [result]
    return result


# ─────────────────────────────────────────────
# STEP 5: HELPER — BUILD .ICS IN MEMORY
# ─────────────────────────────────────────────

def build_ics(medications: list) -> bytes:
    TIMEZONE = pytz.timezone("America/Sao_Paulo")
    DAYS = 7
    patient = medications[0]["patient"]

    cal = Calendar()
    cal.add("prodid", "-//Pet-Med-Parser//pet-med-parser//EN")
    cal.add("version", "2.0")
    cal.add("calname", f"Medicamentos — {patient}")

    now = datetime.now(TIMEZONE)
    start_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    for med in medications:
        medication     = med["medication"]
        dosage_mg      = float(med["dosage_mg"])
        interval_hours = int(med["interval_hours"])
        doses_per_day  = 24 // interval_hours
        total_doses    = doses_per_day * DAYS

        for i in range(total_doses):
            event_start = start_time + timedelta(hours=interval_hours * i)
            event_end   = event_start + timedelta(minutes=15)
            event = Event()
            event.add("summary", f"💊 {patient} — {medication} {dosage_mg}mg")
            event.add("dtstart", event_start)
            event.add("dtend", event_end)
            event.add(
                "description",
                f"Dar para {patient}: {dosage_mg}mg de {medication}.\n"
                f"Gerado pelo Pet-Med-Parser em {now.strftime('%d/%m/%Y')}.",
            )
            cal.add_component(event)

    return cal.to_ical()


# ─────────────────────────────────────────────
# STEP 6: HELPER — SEND EMAIL VIA GMAIL SMTP
# ─────────────────────────────────────────────

def send_email(recipient: str, patient: str, ics_bytes: bytes) -> None:
    """
    Sends the .ics file as an email attachment using Gmail SMTP.
    Requires GMAIL_SENDER and GMAIL_APP_PASSWORD in the .env file.
    Raises an exception if sending fails so the caller can show the error.
    """
    msg = MIMEMultipart()
    msg["From"]    = GMAIL_SENDER
    msg["To"]      = recipient
    msg["Subject"] = f"🐾 Agenda de medicamentos — {patient}"

    body = (
        f"Olá! 😊\n\n"
        f"Segue em anexo a agenda de medicamentos do(a) {patient}.\n\n"
        f"Para importar no Google Agenda:\n"
        f"1. Abra o Google Agenda no celular ou computador\n"
        f"2. Toque no arquivo anexo — ele vai perguntar se quer importar\n"
        f"3. Confirme e pronto! Os lembretes aparecem automaticamente 📅\n\n"
        f"Com carinho, Pet-Med-Parser 🐾"
    )
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Attach the .ics file
    attachment = MIMEBase("text", "calendar")
    attachment.set_payload(ics_bytes)
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        f'attachment; filename="agenda_{patient.lower()}.ics"',
    )
    msg.attach(attachment)

    # Connect to Gmail's SMTP server using TLS (port 587)
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_SENDER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_SENDER, recipient, msg.as_string())


PATIENTS = ["Arya", "Nino", "Aécio"]


# ─────────────────────────────────────────────
# STEP 6: SESSION STATE INITIALISATION
# ─────────────────────────────────────────────
# We use session_state to persist data across Streamlit reruns.
# "stage" controls which screen the user sees:
#   "upload"   → initial screen
#   "review"   → AI flagged something; show manual input form
#   "success"  → everything confirmed; show download button
#   "done"     → user clicked download; reset to upload

for key, default in {
    "stage": "upload",
    "medications": [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# Reset after download
if st.session_state.stage == "done":
    st.session_state.stage = "upload"
    st.session_state.medications = []
    st.rerun()


# ─────────────────────────────────────────────
# STEP 7: HEADER (always visible)
# ─────────────────────────────────────────────

st.title("🐾 Gerenciador de Receitas Pet da Mamãe")
st.markdown("### 🐶 Arya &nbsp;&nbsp; 🦮 Aécio &nbsp;&nbsp; 🐕 Nino")
st.divider()


# ═══════════════════════════════════════════════
# SCREEN A — UPLOAD
# ═══════════════════════════════════════════════

if st.session_state.stage == "upload":

    st.markdown(
        """
        **Faça o upload da foto da receita do veterinário da Arya, do Aécio ou do Nino,
        e eu crio a agenda para você!** 📅

        Depois é só baixar o arquivo e importar no Google Agenda. Simples assim! 😊
        """
    )
    st.divider()

    uploaded_file = st.file_uploader(
        "📷 Escolha a foto da receita",
        type=["jpg", "jpeg", "png"],
        help="Tire uma foto da receita com o celular e faça o upload aqui.",
    )

    if uploaded_file:
        st.image(uploaded_file, caption="Receita enviada ✅", use_container_width=True)
        st.divider()

        if st.button("🔍 Analisar Receita", type="primary", use_container_width=True):
            with st.spinner("🤖 Lendo a letra do veterinário... um momento!"):
                try:
                    medications = call_gemini(uploaded_file.read(), uploaded_file.type)
                except json.JSONDecodeError:
                    st.error("❌ Formato inválido. Tente novamente com uma foto mais nítida.")
                    st.stop()
                except Exception as e:
                    st.error(f"❌ Erro ao chamar a API do Gemini: {e}")
                    st.stop()

            st.session_state.medications = medications

            # Decide next screen based on whether any item needs review
            has_flagged = any(m.get("needs_human_review") for m in medications)
            st.session_state.stage = "review" if has_flagged else "success"
            st.rerun()


# ═══════════════════════════════════════════════
# SCREEN B — MANUAL REVIEW
# Shown when the AI flagged one or more medications as ambiguous.
# The user sees all medications with editable fields for the unclear ones.
# ═══════════════════════════════════════════════

elif st.session_state.stage == "review":

    st.warning(
        "🚨 **ATENÇÃO:** A caligrafia de um ou mais medicamentos está difícil de ler. "
        "Confira os campos marcados em laranja e preencha os valores corretos antes de continuar."
    )
    st.divider()

    medications = st.session_state.medications

    # We build the confirmed list inside a Streamlit form so the user
    # fills everything and submits once — no partial saves.
    with st.form("manual_review_form"):
        st.markdown("### ✏️ Revise e corrija os dados abaixo:")
        confirmed = []

        for i, med in enumerate(medications):
            needs_review = med.get("needs_human_review", False)
            label_suffix = " ⚠️ — preencha manualmente" if needs_review else " ✅"
            st.markdown(f"**Medicamento {i + 1}{label_suffix}**")

            col1, col2, col3 = st.columns(3)

            # Patient: fixed dropdown — AI sometimes misreads names (e.g. "Ana" instead of "Arya")
            ai_patient = med.get("patient") or ""
            default_index = next(
                (j for j, name in enumerate(PATIENTS) if name.lower() == ai_patient.lower()),
                0,  # fallback to first option if no match
            )
            patient = col1.selectbox(
                "Paciente" + (" ⚠️ confira!" if ai_patient not in PATIENTS else ""),
                options=PATIENTS,
                index=default_index,
                key=f"patient_{i}",
            )
            medication = col2.text_input(
                "Medicamento",
                value=med.get("medication") or "",
                key=f"medication_{i}",
            )

            # Dosage: pre-filled if the AI read it, blank if flagged
            dosage_default = str(med["dosage_mg"]) if med.get("dosage_mg") is not None else ""
            dosage_str = col3.text_input(
                "Dosagem (mg)" + (" ⚠️" if needs_review else ""),
                value=dosage_default,
                placeholder="Ex: 2.5",
                key=f"dosage_{i}",
            )

            # Interval: same logic
            interval_default = str(med["interval_hours"]) if med.get("interval_hours") is not None else ""
            interval_str = col1.text_input(
                "Intervalo (horas)" + (" ⚠️" if needs_review else ""),
                value=interval_default,
                placeholder="Ex: 12",
                key=f"interval_{i}",
            )

            confirmed.append({
                "patient":        patient,
                "medication":     medication,
                "_dosage_str":    dosage_str,
                "_interval_str":  interval_str,
            })

            st.divider()

        submitted = st.form_submit_button(
            "✅ Confirmar dados e gerar agenda",
            use_container_width=True,
            type="primary",
        )

    if submitted:
        # Validate that all fields have values before proceeding
        errors = []
        parsed = []
        for i, item in enumerate(confirmed):
            try:
                # Accept both "1.5" (English) and "1,5" (Brazilian) decimal formats
                dosage   = float(item["_dosage_str"].replace(",", "."))
                interval = int(item["_interval_str"].replace(",", "."))
            except ValueError:
                errors.append(
                    f"Medicamento {i + 1} ({item['medication']}): "
                    "dosagem e intervalo precisam ser números."
                )
                continue

            if not item["patient"] or not item["medication"]:
                errors.append(f"Medicamento {i + 1}: paciente e medicamento não podem ficar em branco.")
                continue

            parsed.append({
                "patient":        item["patient"],
                "medication":     item["medication"],
                "dosage_mg":      dosage,
                "interval_hours": interval,
                "needs_human_review": False,
            })

        if errors:
            for err in errors:
                st.error(err)
        else:
            st.session_state.medications = parsed
            st.session_state.stage = "success"
            st.rerun()


# ═══════════════════════════════════════════════
# SCREEN C — SUCCESS + DOWNLOAD
# ═══════════════════════════════════════════════

elif st.session_state.stage == "success":

    medications = st.session_state.medications
    ai_patient  = medications[0]["patient"]

    # Let the user confirm or correct the patient name before downloading.
    # The AI occasionally misreads names (e.g. "Ana" instead of "Arya").
    default_index = next(
        (j for j, name in enumerate(PATIENTS) if name.lower() == ai_patient.lower()),
        0,
    )
    patient = st.selectbox(
        "🐾 Confirme o paciente" + ("" if ai_patient in PATIENTS else f"  ⚠️ (IA leu: '{ai_patient}')"),
        options=PATIENTS,
        index=default_index,
    )

    # Apply the confirmed patient name to all medications
    for med in medications:
        med["patient"] = patient

    st.success(
        f"✅ {len(medications)} medicamento(s) confirmado(s) para **{patient}**!"
    )

    for i, med in enumerate(medications, start=1):
        st.markdown(f"**Medicamento {i}**")
        col1, col2 = st.columns(2)
        col1.metric("💊 Medicamento", med["medication"])
        col1.metric("⚖️ Dosagem", f"{med['dosage_mg']} mg")
        col2.metric("⏰ Intervalo", f"A cada {med['interval_hours']}h")
        col2.metric("🐾 Paciente", med["patient"])
        st.divider()

    ics_bytes = build_ics(medications)

    st.markdown("### 📅 Como você quer enviar a agenda?")
    col_download, col_email = st.columns(2)

    # ── Option 1: Download file ──
    with col_download:
        st.markdown("**💾 Baixar arquivo**")
        st.caption("Salva o arquivo no seu celular/computador para importar manualmente.")
        if st.download_button(
            label="📅 Baixar .ics",
            data=ics_bytes,
            file_name=f"agenda_{patient.lower()}.ics",
            mime="text/calendar",
            use_container_width=True,
            type="primary",
            on_click=lambda: st.session_state.update({"stage": "done"}),
        ):
            st.rerun()

    # ── Option 2: Send via Gmail ──
    with col_email:
        st.markdown("**📧 Enviar por email**")
        st.caption("A agenda chega como anexo — é só tocar para importar.")

        # Only show the email option if Gmail credentials are configured
        if not GMAIL_SENDER or not GMAIL_PASSWORD:
            st.warning("Configure GMAIL_SENDER e GMAIL_APP_PASSWORD no .env para usar esta opção.")
        else:
            with st.form("email_form"):
                recipient = st.text_input(
                    "Email de destino",
                    placeholder="email@gmail.com",
                )
                send_clicked = st.form_submit_button(
                    "📨 Enviar agora",
                    use_container_width=True,
                    type="primary",
                )

            if send_clicked:
                if not recipient or "@" not in recipient:
                    st.error("Por favor, digite um email válido.")
                else:
                    with st.spinner("Enviando email..."):
                        try:
                            send_email(recipient, patient, ics_bytes)
                            st.success(f"✅ Email enviado para **{recipient}**! 🎉")
                            st.info(
                                "Diga para a mamãe abrir o email e tocar no arquivo anexo — "
                                "o Google Agenda vai perguntar se quer importar automaticamente. 📅"
                            )
                            # Reset after a short moment so she can send to another if needed
                            st.session_state.stage = "done"
                        except Exception as e:
                            st.error(f"❌ Erro ao enviar email: {e}")
