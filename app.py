import html
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh
from supabase import create_client

load_dotenv()

st.set_page_config(
    page_title="Monitor Canvas Telegram",
    page_icon="📩",
    layout="wide"
)

# ---------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------
def get_secret_or_env(key: str, default: str = "") -> str:
    try:
        value = st.secrets.get(key, None)
        if value is not None:
            return str(value)
    except Exception:
        pass
    return os.getenv(key, default)


def parse_ids(value: str) -> List[str]:
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


# ---------------------------------------------------------
# SUPABASE
# ---------------------------------------------------------
def get_supabase_client(url: str, key: str):
    if not url or not key:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY.")
    return create_client(url, key)


def supabase_ya_notificado(client, table: str, comment_id: str) -> bool:
    result = (
        client.table(table)
        .select("canvas_comment_id")
        .eq("canvas_comment_id", comment_id)
        .limit(1)
        .execute()
    )
    return bool(result.data)


def supabase_guardar_notificado(client, table: str, data: Dict[str, Any]) -> None:
    payload = {
        "canvas_comment_id": data["comment_id"],
        "course_id": data["course_id"],
        "course_name": data["course_name"],
        "assignment_id": data["assignment_id"],
        "assignment_name": data["assignment_name"],
        "user_id": data["user_id"],
        "student_name": data["student_name"],
        "comment": data["comment"],
        "comment_created_at": data["created_at"],
        "notified_at": datetime.now(timezone.utc).isoformat(),
    }
    client.table(table).upsert(payload, on_conflict="canvas_comment_id").execute()


def supabase_historial(client, table: str, limit: int = 100) -> pd.DataFrame:
    result = (
        client.table(table)
        .select("student_name,course_name,assignment_name,comment,comment_created_at,notified_at")
        .order("notified_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).rename(columns={
        "student_name": "estudiante",
        "course_name": "curso",
        "assignment_name": "actividad",
        "comment": "mensaje",
        "comment_created_at": "fecha_comentario",
        "notified_at": "fecha_alerta",
    })


# ---------------------------------------------------------
# CANVAS API
# ---------------------------------------------------------
def canvas_get(canvas_url: str, token: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{canvas_url.rstrip('/')}/api/v1{endpoint}"
    results = []

    while url:
        response = requests.get(url, headers=headers, params=params, timeout=45)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, list):
            results.extend(data)
        else:
            return data

        url = response.links.get("next", {}).get("url")
        params = None

    return results


def obtener_cursos(canvas_url: str, token: str) -> List[Dict[str, Any]]:
    return canvas_get(
        canvas_url,
        token,
        "/courses",
        params={"enrollment_state": "active", "per_page": 100}
    )


def obtener_actividades(canvas_url: str, token: str, course_id: str) -> List[Dict[str, Any]]:
    return canvas_get(
        canvas_url,
        token,
        f"/courses/{course_id}/assignments",
        params={"per_page": 100}
    )


def obtener_entregas(canvas_url: str, token: str, course_id: str, assignment_id: str) -> List[Dict[str, Any]]:
    return canvas_get(
        canvas_url,
        token,
        f"/courses/{course_id}/assignments/{assignment_id}/submissions",
        params={"include[]": ["submission_comments", "user"], "per_page": 100}
    )


# ---------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------
def enviar_telegram(bot_token: str, chat_id: str, texto: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    response = requests.post(
        url,
        data={"chat_id": chat_id, "text": texto, "parse_mode": "HTML"},
        timeout=45
    )
    response.raise_for_status()


def construir_mensaje(data: Dict[str, Any]) -> str:
    student = html.escape(data.get("student_name", "Sin nombre"))
    course = html.escape(data.get("course_name", "Sin nombre"))
    assignment = html.escape(data.get("assignment_name", "Sin nombre"))
    created_at = html.escape(data.get("created_at", "Sin fecha"))
    comment = html.escape(data.get("comment", ""))

    return f"""📩 <b>Nuevo contacto en Canvas</b>

👤 <b>Estudiante:</b> {student}
📘 <b>Curso:</b> {course}
📝 <b>Actividad:</b> {assignment}
🕒 <b>Fecha:</b> {created_at}

💬 <b>Mensaje:</b>
{comment}
"""


# ---------------------------------------------------------
# REVISIÓN PRINCIPAL
# ---------------------------------------------------------
def revisar_y_notificar(
    canvas_url: str,
    canvas_token: str,
    telegram_token: str,
    telegram_chat_id: str,
    cursos_seleccionados: List[Dict[str, Any]],
    supabase_client: Any,
    supabase_table: str,
):
    total_nuevos = 0
    registros = []
    errores = []

    for curso in cursos_seleccionados:
        course_id = str(curso["id"])
        course_name = curso.get("name", "Sin nombre")

        try:
            actividades = obtener_actividades(canvas_url, canvas_token, course_id)

            for actividad in actividades:
                assignment_id = str(actividad["id"])
                assignment_name = actividad.get("name", "Sin nombre")
                entregas = obtener_entregas(canvas_url, canvas_token, course_id, assignment_id)

                for entrega in entregas:
                    user = entrega.get("user", {}) or {}
                    student_name = user.get("name", "Sin nombre")
                    user_id = str(entrega.get("user_id", ""))
                    comentarios = entrega.get("submission_comments", []) or []

                    for comment_obj in comentarios:
                        comment_id = str(comment_obj.get("id", ""))
                        comment_text = comment_obj.get("comment", "") or ""

                        if not comment_id or not comment_text.strip():
                            continue

                        if supabase_ya_notificado(supabase_client, supabase_table, comment_id):
                            continue

                        data = {
                            "comment_id": comment_id,
                            "course_id": course_id,
                            "course_name": course_name,
                            "assignment_id": assignment_id,
                            "assignment_name": assignment_name,
                            "user_id": user_id,
                            "student_name": student_name,
                            "comment": comment_text,
                            "created_at": comment_obj.get("created_at", "")
                        }

                        enviar_telegram(telegram_token, telegram_chat_id, construir_mensaje(data))
                        supabase_guardar_notificado(supabase_client, supabase_table, data)

                        total_nuevos += 1
                        registros.append(data)

        except Exception as e:
            errores.append(f"{course_name}: {e}")

    return total_nuevos, registros, errores


# ---------------------------------------------------------
# INTERFAZ
# ---------------------------------------------------------
st.title("📩 Monitor de Contactos Canvas → Telegram")
st.caption("Detecta comentarios nuevos en entregas de Canvas, evita duplicados con Supabase y envía alertas automáticas a Telegram.")

with st.sidebar:
    st.header("⚙️ Configuración")

    canvas_url = st.text_input("URL de Canvas", value=get_secret_or_env("CANVAS_URL", "https://uvg.instructure.com"))
    canvas_token = st.text_input("Token de Canvas", value=get_secret_or_env("CANVAS_TOKEN", ""), type="password")
    telegram_token = st.text_input("Token del bot de Telegram", value=get_secret_or_env("TELEGRAM_BOT_TOKEN", ""), type="password")
    telegram_chat_id = st.text_input("Chat ID de Telegram", value=get_secret_or_env("TELEGRAM_CHAT_ID", ""))

    st.divider()
    st.subheader("Supabase")
    supabase_url = st.text_input("Supabase URL", value=get_secret_or_env("SUPABASE_URL", ""))
    supabase_key = st.text_input("Supabase Key", value=get_secret_or_env("SUPABASE_KEY", ""), type="password")
    supabase_table = st.text_input("Tabla Supabase", value=get_secret_or_env("SUPABASE_TABLE", "canvas_alertas_notificadas"))

    st.divider()
    st.subheader("Monitoreo")
    monitoreo_activo = st.toggle("Activar monitoreo automático cada hora", value=False)
    course_ids_secret = get_secret_or_env("MONITORED_COURSE_IDS", "")

    if monitoreo_activo:
        st_autorefresh(interval=60 * 60 * 1000, key="auto_refresh_hora")
        st.success("Monitoreo activo: revisión cada 1 hora.")
    else:
        st.info("Monitoreo automático desactivado.")

faltantes = []
if not canvas_token:
    faltantes.append("Token de Canvas")
if not telegram_token:
    faltantes.append("Token del bot de Telegram")
if not telegram_chat_id:
    faltantes.append("Chat ID de Telegram")
if not supabase_url:
    faltantes.append("Supabase URL")
if not supabase_key:
    faltantes.append("Supabase Key")
if not supabase_table:
    faltantes.append("Tabla Supabase")

if faltantes:
    st.warning("Completa estos datos para iniciar: " + ", ".join(faltantes))
    st.stop()

try:
    supabase_client = get_supabase_client(supabase_url, supabase_key)
except Exception as e:
    st.error(f"No se pudo conectar con Supabase: {e}")
    st.stop()

col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    cargar = st.button("🔍 Cargar cursos activos")
with col2:
    probar_telegram = st.button("📲 Probar Telegram")

if probar_telegram:
    try:
        enviar_telegram(telegram_token, telegram_chat_id, "✅ Prueba correcta: Monitor Canvas → Telegram conectado.")
        st.success("Mensaje de prueba enviado a Telegram.")
    except Exception as e:
        st.error(f"No se pudo enviar el mensaje de prueba: {e}")

if cargar or "cursos" not in st.session_state:
    try:
        cursos = obtener_cursos(canvas_url, canvas_token)
        cursos = [c for c in cursos if c.get("id") and c.get("name")]
        st.session_state["cursos"] = cursos
        if cargar:
            st.success(f"Se cargaron {len(cursos)} cursos activos.")
    except Exception as e:
        st.error(f"No se pudieron cargar los cursos: {e}")
        st.stop()

cursos = st.session_state.get("cursos", [])
opciones_cursos = {f'{c.get("name", "Sin nombre")} | ID: {c.get("id")}': c for c in cursos}

ids_preseleccionados = set(parse_ids(course_ids_secret))
def default_labels():
    return [label for label, curso in opciones_cursos.items() if str(curso.get("id")) in ids_preseleccionados]

seleccion_labels = st.multiselect(
    "Cursos a monitorear",
    options=list(opciones_cursos.keys()),
    default=default_labels()
)
cursos_seleccionados = [opciones_cursos[label] for label in seleccion_labels]

ejecutar_revision = st.button("🚨 Revisar comentarios ahora")
if monitoreo_activo and cursos_seleccionados:
    ejecutar_revision = True

if ejecutar_revision:
    if not cursos_seleccionados:
        st.warning("Selecciona al menos un curso para monitorear.")
    else:
        with st.spinner("Revisando comentarios en entregas..."):
            total_nuevos, registros, errores = revisar_y_notificar(
                canvas_url=canvas_url,
                canvas_token=canvas_token,
                telegram_token=telegram_token,
                telegram_chat_id=telegram_chat_id,
                cursos_seleccionados=cursos_seleccionados,
                supabase_client=supabase_client,
                supabase_table=supabase_table
            )

        st.success(f"Revisión finalizada. Alertas nuevas enviadas: {total_nuevos}")

        if registros:
            st.dataframe(pd.DataFrame(registros), use_container_width=True)

        if errores:
            st.warning("Algunos cursos presentaron errores:")
            for err in errores:
                st.write(f"- {err}")

st.divider()
st.subheader("📚 Últimas alertas enviadas")

try:
    historial = supabase_historial(supabase_client, supabase_table, limit=100)
    if not historial.empty:
        st.dataframe(historial, use_container_width=True)
    else:
        st.info("Aún no hay alertas registradas en Supabase.")
except Exception as e:
    st.error(f"No se pudo cargar el historial desde Supabase: {e}")
