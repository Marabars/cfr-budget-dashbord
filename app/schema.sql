-- Схема БД дашборда бюджетов ЦФО.
-- Единицы: рубли с копейками (REAL), всегда с НДС. Год — отдельное поле, архив по годам.
PRAGMA foreign_keys = ON;

-- ---------- справочники ----------
CREATE TABLE IF NOT EXISTS cfo (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE,       -- каноничное название дирекции
  parent_id INTEGER REFERENCES cfo(id), -- иерархия (используется редко)
  active    INTEGER NOT NULL DEFAULT 1,
  -- что показывать в колонке «Детализация»: свой комментарий или детализацию из бюджета
  detail_source TEXT NOT NULL DEFAULT 'comment'   -- comment | detail
);

-- варианты написания названий ЦФО из выгрузок -> каноничный ЦФО
CREATE TABLE IF NOT EXISTS cfo_alias (
  alias  TEXT PRIMARY KEY,
  cfo_id INTEGER NOT NULL REFERENCES cfo(id) ON DELETE CASCADE
);

-- Бюджет живёт в одном из двух слоёв:
--   main     — исполнение текущего года: дашборд, сводка, карточка ЦФО, факт из 1С;
--   operplan — планирование на вкладке «Оперплан»: лист «Бюджеты ЦФО» и план будущего года.
-- Слои не смешиваются: запросы исполнения всегда спрашивают layer = 'main'.
CREATE TABLE IF NOT EXISTS budget (
  id     INTEGER PRIMARY KEY,
  cfo_id INTEGER NOT NULL REFERENCES cfo(id) ON DELETE CASCADE,
  year   INTEGER NOT NULL,
  name   TEXT NOT NULL,                 -- «Бюджет обязательных затрат», «Бюджет развития», «Основной бюджет»
  layer  TEXT NOT NULL DEFAULT 'main',  -- main | operplan
  UNIQUE (cfo_id, year, name, layer)
);

-- ---------- строки бюджета ----------
CREATE TABLE IF NOT EXISTS budget_row (
  id                INTEGER PRIMARY KEY,
  budget_id         INTEGER NOT NULL REFERENCES budget(id) ON DELETE CASCADE,
  row_no            INTEGER,            -- № строки внутри бюджета (как в Excel)
  article           TEXT NOT NULL,      -- «4420_Расходы на приобретение ПО»
  counterparty      TEXT NOT NULL DEFAULT '',
  contract          TEXT NOT NULL DEFAULT '',
  detail            TEXT NOT NULL DEFAULT '',
  comment           TEXT NOT NULL DEFAULT '',
  approver_comment  TEXT NOT NULL DEFAULT '',  -- колонка «Комм наш»
  plan_year         REAL NOT NULL DEFAULT 0,   -- колонка «БЮДЖЕТ» — утверждённый годовой лимит
  carryover         INTEGER NOT NULL DEFAULT 1,-- переносить неиспользованный остаток на след. месяц
  source            TEXT NOT NULL DEFAULT 'manual',  -- import | manual
  created_by        TEXT NOT NULL DEFAULT '',
  created_at        TEXT NOT NULL DEFAULT (datetime('now')),
  deleted_at        TEXT                        -- мягкое удаление: строку видно в журнале
);
CREATE INDEX IF NOT EXISTS ix_row_budget ON budget_row(budget_id) WHERE deleted_at IS NULL;

-- план по месяцам (1..12)
CREATE TABLE IF NOT EXISTS budget_row_month (
  row_id INTEGER NOT NULL REFERENCES budget_row(id) ON DELETE CASCADE,
  month  INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  amount REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (row_id, month)
);

-- ---------- факт слоя планирования ----------
-- Факт по строкам плана в той же помесячной форме, что и план. Живёт отдельно
-- от таблицы fact: там факт — это платежи из 1С, привязанные к слою исполнения,
-- а здесь суммы, загруженные Excel'ем прямо на строку бюджета прошлого года.
CREATE TABLE IF NOT EXISTS budget_row_fact_month (
  row_id INTEGER NOT NULL REFERENCES budget_row(id) ON DELETE CASCADE,
  month  INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
  amount REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (row_id, month)
);

-- ---------- заявки (обязательства) ----------
CREATE TABLE IF NOT EXISTS claim (
  id            INTEGER PRIMARY KEY,
  row_id        INTEGER REFERENCES budget_row(id) ON DELETE SET NULL,
  cfo_id        INTEGER NOT NULL REFERENCES cfo(id),
  year          INTEGER NOT NULL,
  number_1c     TEXT NOT NULL DEFAULT '',
  pay_date      TEXT NOT NULL,          -- YYYY-MM-DD, плановая дата платежа
  amount        REAL NOT NULL,
  counterparty  TEXT NOT NULL DEFAULT '',
  contract      TEXT NOT NULL DEFAULT '',
  detail        TEXT NOT NULL DEFAULT '',
  out_of_budget INTEGER NOT NULL DEFAULT 0,
  over_limit    INTEGER NOT NULL DEFAULT 0,   -- сохранена сверх свободного лимита
  status        TEXT NOT NULL DEFAULT 'planned', -- planned | paid | cancelled
  created_by    TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_claim_row ON claim(row_id);
CREATE INDEX IF NOT EXISTS ix_claim_cfo ON claim(cfo_id, year);

-- ---------- факт ----------
CREATE TABLE IF NOT EXISTS fact (
  id            INTEGER PRIMARY KEY,
  row_id        INTEGER REFERENCES budget_row(id) ON DELETE SET NULL, -- NULL = не сопоставлен
  cfo_id        INTEGER REFERENCES cfo(id),
  year          INTEGER NOT NULL,
  pay_date      TEXT NOT NULL,
  amount        REAL NOT NULL,
  article       TEXT NOT NULL DEFAULT '',
  counterparty  TEXT NOT NULL DEFAULT '',
  contract      TEXT NOT NULL DEFAULT '',
  purpose       TEXT NOT NULL DEFAULT '',
  claim_number  TEXT NOT NULL DEFAULT '',   -- № заявки 1С для автосхлопывания
  out_of_budget INTEGER NOT NULL DEFAULT 0,
  source        TEXT NOT NULL DEFAULT 'manual', -- 1c | excel | manual | operplan
  external_id   TEXT,                       -- ключ идемпотентности повторной загрузки
  matched_by    TEXT NOT NULL DEFAULT '',
  matched_at    TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (external_id)
);
CREATE INDEX IF NOT EXISTS ix_fact_row ON fact(row_id);
CREATE INDEX IF NOT EXISTS ix_fact_unmatched ON fact(year) WHERE row_id IS NULL AND out_of_budget = 0;

-- ---------- корректировки лимитов ----------
CREATE TABLE IF NOT EXISTS adjustment (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,             -- month | row
  year        INTEGER NOT NULL,
  cfo_id      INTEGER NOT NULL REFERENCES cfo(id),
  from_row_id INTEGER REFERENCES budget_row(id),
  to_row_id   INTEGER REFERENCES budget_row(id),
  from_month  INTEGER,
  to_month    INTEGER,
  amount      REAL NOT NULL,
  reason      TEXT NOT NULL,
  author      TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------- журнал изменений ----------
CREATE TABLE IF NOT EXISTS audit_log (
  id         INTEGER PRIMARY KEY,
  ts         TEXT NOT NULL DEFAULT (datetime('now')),
  author     TEXT NOT NULL DEFAULT '',
  action     TEXT NOT NULL,
  object     TEXT NOT NULL DEFAULT '',
  change     TEXT NOT NULL DEFAULT '',    -- «было → стало»
  reason     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts DESC);

-- ---------- загрузки файлов ----------
CREATE TABLE IF NOT EXISTS import_batch (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,             -- operplan | plan | fact
  filename    TEXT NOT NULL,
  year        INTEGER NOT NULL,
  uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
  author      TEXT NOT NULL DEFAULT '',
  rows_ok     INTEGER NOT NULL DEFAULT 0,
  rows_error  INTEGER NOT NULL DEFAULT 0,
  mapping     TEXT NOT NULL DEFAULT '',   -- JSON сопоставления колонок
  note        TEXT NOT NULL DEFAULT ''
);

-- Справочник статей ЦФО (лист «ЦФО Статьи» файла ликвидности).
-- Источник 'ref' — утверждённое соответствие, 'used' — статья реально встречается в строках.
CREATE TABLE IF NOT EXISTS article_ref (
  cfo_id  INTEGER NOT NULL REFERENCES cfo(id) ON DELETE CASCADE,
  article TEXT NOT NULL,
  PRIMARY KEY (cfo_id, article)
);

-- запомненное сопоставление колонок для файлов дирекции
CREATE TABLE IF NOT EXISTS column_mapping (
  cfo_id  INTEGER PRIMARY KEY REFERENCES cfo(id) ON DELETE CASCADE,
  mapping TEXT NOT NULL
);

-- ---------- пользователи и настройки ----------
CREATE TABLE IF NOT EXISTS app_user (
  login TEXT PRIMARY KEY,
  name  TEXT NOT NULL,
  role  TEXT NOT NULL DEFAULT 'cfo',     -- fin | cfo
  cfo_ids TEXT NOT NULL DEFAULT '',      -- список id через запятую для роли cfo
  password_hash TEXT NOT NULL DEFAULT '',-- пусто = учётка ещё без пароля, войти нельзя
  is_active INTEGER NOT NULL DEFAULT 1
);

-- Сессии входа. Пока ни у кого нет пароля, таблица пустует, а приложение
-- работает в режиме доверенной сети (см. app/auth.py).
CREATE TABLE IF NOT EXISTS session (
  token      TEXT PRIMARY KEY,
  login      TEXT NOT NULL REFERENCES app_user(login) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_session_login ON session(login);

CREATE TABLE IF NOT EXISTS setting (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);