-- Items the pipeline could not process (for now): retried with growing delays, then abandoned and kept for operators.
-- The queue never holds article text, only the identifiers needed to fetch it again.
CREATE TABLE dead_letters (
    id              bigserial PRIMARY KEY,
    kind            text        NOT NULL CHECK (kind IN ('article')),
    ref             text        NOT NULL,
    payload         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status          text        NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'done', 'abandoned')),
    attempts        integer     NOT NULL DEFAULT 1,
    last_error      text,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (kind, ref)
);
CREATE INDEX dead_letters_due_ix ON dead_letters (next_attempt_at) WHERE status = 'queued';

-- The sources page shows queue depth only.
GRANT SELECT (id, kind, status, attempts, next_attempt_at, updated_at) ON dead_letters TO meridian_app;
