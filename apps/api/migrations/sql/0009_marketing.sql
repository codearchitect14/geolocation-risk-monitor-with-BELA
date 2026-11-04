-- Marketing site support: richer demo requests and a double opt-in newsletter list.
ALTER TABLE demo_requests ADD COLUMN role text;
ALTER TABLE demo_requests ADD COLUMN industry text;
ALTER TABLE demo_requests ADD COLUMN consent_at timestamptz;

CREATE TABLE newsletter_subscribers (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text NOT NULL,
    token_hash    text NOT NULL,
    confirmed_at  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX newsletter_subscribers_email_ix ON newsletter_subscribers (lower(email));
CREATE INDEX newsletter_subscribers_token_ix ON newsletter_subscribers (token_hash);
