-- Wipe all conversation data, keeping the brand and agent accounts.
-- Run before submission (or whenever you want a clean inbox), then run seed.sql
-- again to put the test customers back.
--
-- One statement for all four tables: messages and drafts reference each other,
-- so they have to be truncated together.

truncate table drafts, messages, conversations, customers;
