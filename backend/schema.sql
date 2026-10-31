-- Verdant & Co support inbox: database schema.
-- Run once in the Supabase SQL editor (or psql) on an empty project.
-- Runs in one transaction: if any statement fails, nothing is created.
--
-- Every table carries brand_id, so adding brands is a data change, not a migration.
-- Correctness rules (no duplicate messages, one open conversation per customer,
-- one active draft, one reply per draft) are enforced here by constraints, so
-- concurrent requests can't race past an application-level check.

begin;

create table brands (
  id         text primary key,                -- 'verdant-co' (matches webhook brand_id)
  name       text not null,
  created_at timestamptz not null default now()
);

-- Which Supabase Auth users are agents, and for which brand.
-- Signing in proves who you are; a row here is what makes you an agent.
create table agents (
  user_id      uuid primary key references auth.users(id) on delete cascade,
  brand_id     text not null references brands(id),
  display_name text not null
);

create table customers (
  id          uuid primary key default gen_random_uuid(),
  brand_id    text not null references brands(id),
  external_id text not null,                   -- 'cust_1042' from the chat platform
  name        text not null,
  phone       text not null,
  created_at  timestamptz not null default now(),
  unique (brand_id, external_id)
);

create table conversations (
  id                   uuid primary key default gen_random_uuid(),
  brand_id             text not null references brands(id),
  customer_id          uuid not null references customers(id),
  status               text not null default 'open' check (status in ('open', 'closed')),
  -- Copied from the newest message, so the inbox list is one indexed query.
  last_message_at      timestamptz not null default now(),
  last_message_preview text not null default '',
  created_at           timestamptz not null default now()
);
-- A customer can have many closed conversations but only one open one.
create unique index one_open_conversation_per_customer
  on conversations (customer_id) where status = 'open';
create index conversations_inbox on conversations (brand_id, last_message_at desc);

create table messages (
  id              uuid primary key default gen_random_uuid(),
  brand_id        text not null references brands(id),
  conversation_id uuid not null references conversations(id),
  sender          text not null check (sender in ('customer', 'agent')),
  body            text not null check (char_length(body) between 1 and 4000),
  event_id        text,          -- webhook event_id   (customer messages only)
  external_id     text,          -- webhook message.id (customer messages only)
  sent_at         timestamptz,   -- timestamp claimed in the payload, kept for reference
  created_at      timestamptz not null default now(),  -- when we stored it; used for ordering
  agent_id        uuid references agents(user_id),     -- agent replies only
  source_draft_id uuid unique,   -- the draft an agent reply was approved from (one reply per draft)
  -- Idempotency: a retried delivery (same event_id) or a re-sent message
  -- (same message.id under a new event_id) can't be stored twice.
  unique (brand_id, event_id),
  unique (brand_id, external_id),
  check (
    (sender = 'customer' and event_id is not null and external_id is not null and agent_id is null)
    or
    (sender = 'agent' and agent_id is not null and event_id is null and external_id is null)
  )
);
create index messages_by_conversation on messages (conversation_id, created_at);

-- Drafts live in their own table, never in messages. Customer-facing endpoints
-- only read messages, so a draft can't reach the Customer view by accident.
create table drafts (
  id              uuid primary key default gen_random_uuid(),
  brand_id        text not null references brands(id),
  conversation_id uuid not null references conversations(id),
  message_id      uuid not null unique references messages(id),  -- the customer message it answers
  status          text not null default 'pending'
                  check (status in ('pending', 'ready', 'failed', 'approved', 'superseded')),
  body            text,          -- the AI's original suggestion (kept even after an agent edits it)
  needs_human     boolean not null default false,
  flag_reason     text,          -- e.g. 'Not in knowledge base: international delivery'
  error           text,          -- last failure, shown to the agent
  attempts        int not null default 0,
  model           text,          -- which LLM wrote it (primary or fallback)
  approved_by     uuid references agents(user_id),
  approved_at     timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  check ((status = 'approved') = (approved_by is not null and approved_at is not null))
);
-- At most one draft per conversation is waiting for an agent; a newer
-- customer message supersedes the old one.
create unique index one_active_draft_per_conversation
  on drafts (conversation_id) where status in ('pending', 'ready', 'failed');

-- Added after both tables exist (messages and drafts reference each other).
alter table messages
  add constraint messages_source_draft_fk foreign key (source_draft_id) references drafts(id);

-- Deny-all row-level security: RLS on, no policies. Supabase's public REST API
-- (whose anon key ships in the frontend) can read and write nothing.
-- The backend connects to Postgres directly as the table owner, which bypasses RLS.
alter table brands        enable row level security;
alter table agents        enable row level security;
alter table customers     enable row level security;
alter table conversations enable row level security;
alter table messages      enable row level security;
alter table drafts        enable row level security;

commit;
