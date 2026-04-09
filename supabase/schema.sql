create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

create table if not exists public.member_accounts (
  id uuid primary key default gen_random_uuid(),
  telegram_chat_id text not null unique,
  telegram_username text,
  display_name text,
  club text not null default 'Bolueta',
  gym_username_ciphertext text not null,
  gym_password_ciphertext text not null,
  active boolean not null default true,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.booking_requests (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.member_accounts(id) on delete cascade,
  club text not null default 'Bolueta',
  day text not null,
  time text not null,
  class_name text not null,
  target_date date,
  interval_seconds integer not null default 120,
  watch_until timestamptz not null,
  status text not null default 'pending'
    check (status in ('pending', 'booked', 'expired', 'cancelled', 'error')),
  attempts integer not null default 0,
  last_result text,
  last_checked_at timestamptz,
  booked_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists booking_requests_status_idx
  on public.booking_requests (status, watch_until);

drop trigger if exists trg_member_accounts_updated_at on public.member_accounts;
create trigger trg_member_accounts_updated_at
before update on public.member_accounts
for each row
execute function public.set_updated_at();

drop trigger if exists trg_booking_requests_updated_at on public.booking_requests;
create trigger trg_booking_requests_updated_at
before update on public.booking_requests
for each row
execute function public.set_updated_at();

alter table public.member_accounts disable row level security;
alter table public.booking_requests disable row level security;
