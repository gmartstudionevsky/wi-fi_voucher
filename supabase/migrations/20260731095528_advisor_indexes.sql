create index if not exists idx_access_invites_hotel
    on wifi_voucher.access_invites(hotel_id);

create index if not exists idx_audit_user
    on wifi_voucher.audit_events(user_id)
    where user_id is not null;
