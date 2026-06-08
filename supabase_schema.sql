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
