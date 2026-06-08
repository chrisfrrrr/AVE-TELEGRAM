# Monitor Canvas → Telegram

Aplicación independiente en Streamlit para revisar comentarios nuevos que los estudiantes dejan en entregas de actividades de Canvas y enviarlos automáticamente a Telegram.

Esta versión usa **Supabase como única base de datos**. No utiliza SQLite ni archivos locales para guardar historial.

## Funciones

- Conexión con Canvas API.
- Selección de cursos activos.
- Revisión de actividades y entregas.
- Detección de `submission_comments`.
- Envío de alertas a Telegram.
- Control de duplicados usando Supabase.
- Historial de alertas desde Supabase.
- Revisión automática cada 1 hora mientras la app esté activa.
- Preselección opcional de cursos por variable `MONITORED_COURSE_IDS`.

## Instalación local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Variables recomendadas en Streamlit Secrets

En Streamlit Cloud, colocar esto en **Secrets**:

```toml
CANVAS_URL = "https://uvg.instructure.com"
CANVAS_TOKEN = "tu_token_canvas"
TELEGRAM_BOT_TOKEN = "tu_token_bot"
TELEGRAM_CHAT_ID = "tu_chat_id"

SUPABASE_URL = "https://xxxxxxxx.supabase.co"
SUPABASE_KEY = "tu_anon_key_o_service_role_key"
SUPABASE_TABLE = "canvas_alertas_notificadas"

# Opcional: IDs de cursos separados por coma.
MONITORED_COURSE_IDS = "12345,67890"
```

## Tabla en Supabase

Ejecutar en el SQL Editor de Supabase:

```sql
create table if not exists canvas_alertas_notificadas (
  id bigserial primary key,
  canvas_comment_id text unique not null,
  course_id text,
  course_name text,
  assignment_id text,
  assignment_name text,
  user_id text,
  student_name text,
  comment text,
  comment_created_at timestamptz,
  notified_at timestamptz default now()
);

create index if not exists idx_canvas_alertas_notificadas_comment_id
on canvas_alertas_notificadas (canvas_comment_id);

create index if not exists idx_canvas_alertas_notificadas_notified_at
on canvas_alertas_notificadas (notified_at desc);
```

## Revisión automática

La app usa `streamlit-autorefresh` para recargar cada hora cuando el monitoreo automático está activado. Para que funcione, la app debe permanecer abierta o desplegada en un servidor activo. En Streamlit Community Cloud puede dormirse si no hay actividad.

## Notas de seguridad

- No subas tokens reales al repositorio.
- Usa `secrets.toml` en Streamlit Cloud o variables de entorno.
- La tabla de Supabase contiene mensajes de estudiantes; debe manejarse como información sensible institucional.
