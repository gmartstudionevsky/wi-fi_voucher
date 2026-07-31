-- Email invitations are private and become memberships automatically when the
-- invited employee first signs in through Supabase Auth.

create table if not exists wifi_voucher.access_invites (
    email text not null,
    hotel_id text not null references wifi_voucher.hotels(id) on delete cascade,
    role text not null default 'operator'
        check (role in ('admin', 'operator', 'viewer')),
    active boolean not null default true,
    created_at timestamptz not null default now(),
    accepted_at timestamptz,
    primary key (email, hotel_id),
    check (email = lower(btrim(email)))
);

alter table wifi_voucher.access_invites enable row level security;
revoke all on table wifi_voucher.access_invites from public, anon, authenticated;

create or replace function wifi_voucher.accept_access_invites()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, wifi_voucher
as $$
begin
    insert into wifi_voucher.memberships(user_id, hotel_id, role, display_name)
    select new.id, i.hotel_id, i.role,
           coalesce(new.raw_user_meta_data ->> 'full_name', split_part(new.email, '@', 1))
    from wifi_voucher.access_invites i
    where i.email = lower(new.email)
      and i.active
    on conflict (user_id, hotel_id) do update
    set role = excluded.role, active = true;

    update wifi_voucher.access_invites i
    set accepted_at = now()
    where i.email = lower(new.email) and i.active;
    return new;
end;
$$;

revoke all on function wifi_voucher.accept_access_invites() from public, anon, authenticated;

drop trigger if exists on_wifi_voucher_auth_user_created on auth.users;
create trigger on_wifi_voucher_auth_user_created
    after insert or update of email on auth.users
    for each row execute function wifi_voucher.accept_access_invites();

-- Invitations are provisioned separately so employee email addresses are not
-- stored in the public repository. This also covers users created before an
-- invitation is added.
insert into wifi_voucher.memberships(user_id, hotel_id, role, display_name)
select u.id, i.hotel_id, i.role,
       coalesce(u.raw_user_meta_data ->> 'full_name', split_part(u.email, '@', 1))
from auth.users u
join wifi_voucher.access_invites i on i.email = lower(u.email)
where i.active
on conflict (user_id, hotel_id) do update
set role = excluded.role, active = true;
