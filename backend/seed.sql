-- Seed data: the brand, test customers for the Customer view, and agent links.
-- Safe to run any number of times (every insert skips rows that already exist).
--
-- Before running: create the agent users in Supabase (Authentication > Users >
-- Add user, "Auto confirm user" ticked). If you used different emails than the
-- ones below, edit the `agent_emails` list.

begin;

insert into brands (id, name)
values ('verdant-co', 'Verdant & Co')
on conflict (id) do nothing;

-- Test customers offered in the Customer view. Aisha matches the brief's sample webhook.
insert into customers (brand_id, external_id, name, phone)
values
  ('verdant-co', 'cust_1042', 'Aisha Khan',  '+919800000001'),
  ('verdant-co', 'cust_1043', 'Rohan Mehta', '+919800000002'),
  ('verdant-co', 'cust_1044', 'Meera Iyer',  '+919800000003')
on conflict (brand_id, external_id) do nothing;

-- Link Supabase Auth users to the brand as agents, matched by email.
-- A user with no row here can sign in but gets 403 from every agent endpoint.
insert into agents (user_id, brand_id, display_name)
select u.id, 'verdant-co', agent_emails.display_name
from (values
  ('priya@example.com', 'Priya'),
  ('rahul@example.com', 'Rahul')
) as agent_emails (email, display_name)
join auth.users u on lower(u.email) = agent_emails.email
on conflict (user_id) do nothing;

commit;

-- Check: expect one row per agent. No rows means the Auth users don't exist yet
-- or their emails don't match the list above.
select a.display_name, u.email, a.brand_id
from agents a join auth.users u on u.id = a.user_id
order by a.display_name;
