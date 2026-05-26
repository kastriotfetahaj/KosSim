-- Load extensions

CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS tsm_system_rows;



-- Credentials for DB users

CREATE OR REPLACE FUNCTION __create_user(username VARCHAR, password VARCHAR) RETURNS void AS $$
    BEGIN
        EXECUTE format('CREATE USER %I WITH PASSWORD %L', username, password);
    END;
$$ LANGUAGE plpgsql;

SELECT __create_user('anonymous',      'anonymous');
SELECT __create_user('authentication', trim(pg_read_file('/state/db/secrets/authentication')));
SELECT __create_user('stats',          trim(pg_read_file('/state/db/secrets/stats')));
SELECT __create_user('ftp',            trim(pg_read_file('/state/db/secrets/ftp')));

DROP FUNCTION __create_user;

REVOKE ALL ON ALL TABLES IN SCHEMA information_schema FROM anonymous, authentication, ftp, public, stats;
REVOKE ALL ON ALL TABLES IN SCHEMA pg_catalog FROM anonymous, authentication, ftp, public, stats;
REVOKE ALL ON SCHEMA cron FROM anonymous, authentication, ftp, public, stats;

GRANT pg_use_reserved_connections TO authentication, ftp;

GRANT CREATE ON SCHEMA public TO stats; -- This will be revoked at the very end. We need it to create stats functions.

DO $$
    DECLARE
        fn RECORD;
    BEGIN
        FOR fn IN
            SELECT n.nspname AS schema, p.proname AS name, pg_get_function_arguments(p.oid) AS args
                FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
                WHERE n.nspname = 'pg_catalog' AND p.prokind = 'f' AND
                    (p.proname LIKE 'pg_%' OR p.proname LIKE 'plpgsql%')
        LOOP
            BEGIN
                EXECUTE format('REVOKE EXECUTE ON FUNCTION %I.%I(%s) FROM anonymous, public;',
                    fn.schema, fn.name, fn.args);
                EXECUTE format('GRANT EXECUTE ON FUNCTION %I.%I(%s) TO authentication, ftp, stats;',
                    fn.schema, fn.name, fn.args);
            EXCEPTION
                WHEN OTHERS THEN
                    RAISE NOTICE 'Failed to restrict access to function %.%(%)',
                        fn.schema, fn.name, fn.args;
            END;
        END LOOP;
    END
$$;



-- Timeouts

ALTER SYSTEM SET authentication_timeout = '5s';
ALTER ROLE anonymous SET idle_in_transaction_session_timeout = '1s';
ALTER ROLE anonymous SET idle_session_timeout = '30s';
ALTER ROLE anonymous SET lock_timeout = '5s';
ALTER ROLE anonymous SET statement_timeout = '1s';
ALTER ROLE anonymous SET tcp_user_timeout = '1s';
ALTER ROLE anonymous SET transaction_timeout = '5s';



-- User accounts

CREATE OR REPLACE FUNCTION generate_user_identifier() RETURNS bigint AS $$
    DECLARE
        value bigint;
        conflict INTEGER;
    BEGIN
        PERFORM pg_advisory_xact_lock(hashtext('generate_user_identifier'));
        LOOP
            SELECT ('x' || encode(gen_random_bytes(8), 'hex'))::bit(64)::bigint INTO value;
            SELECT count(*) INTO conflict FROM users WHERE identifier = value LIMIT 1;
            IF conflict = 0 THEN
                RETURN value;
            END IF;
        END LOOP;
    END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS users
(
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    identifier   bigint UNIQUE NOT NULL DEFAULT generate_user_identifier(),
    name         VARCHAR(64) UNIQUE NOT NULL,
    password     VARCHAR(128) NOT NULL,
    created      timestamp NOT NULL DEFAULT now()
);
REVOKE ALL ON TABLE users FROM anonymous, authentication, ftp, public, stats;
GRANT ALL ON TABLE users TO authentication;
GRANT SELECT ON TABLE users TO ftp, stats;

CREATE INDEX IF NOT EXISTS idx_users_by_identifier ON users (identifier);
CREATE INDEX IF NOT EXISTS idx_users_by_creation ON users (created);

SET ROLE stats;
CREATE OR REPLACE FUNCTION user_by_identifier(ident bigint) RETURNS VARCHAR AS $$
    DECLARE
        username VARCHAR;
    BEGIN
        SELECT name INTO username FROM public.users WHERE identifier = ident LIMIT 1;
        RETURN username;
    END;
$$ LANGUAGE plpgsql
   PARALLEL SAFE STABLE STRICT
   SECURITY DEFINER
   SET search_path = public;
RESET ROLE;



-- IP allocations for each user

CREATE TABLE IF NOT EXISTS ips
(
    ip          inet UNIQUE NOT NULL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE
) PARTITION BY RANGE (ip);

CREATE TABLE IF NOT EXISTS ips_ipv4 PARTITION OF ips
    FOR VALUES FROM ('0.0.0.0'::inet) TO ('255.255.255.255'::inet);
CREATE TABLE IF NOT EXISTS ips_ipv6 PARTITION OF ips
    FOR VALUES FROM ('::'::inet) TO ('ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff'::inet);
SET enable_partition_pruning = ON;

CREATE INDEX IF NOT EXISTS idx_ips_by_user ON ips (user_id);

REVOKE ALL ON TABLE ips FROM anonymous, authentication, ftp, public, stats;
GRANT ALL ON TABLE ips TO authentication;



-- IP allocation utilities

CREATE TABLE IF NOT EXISTS ip_ranges
(
    -- We maintain a list of free CIDR blocks for faster allocation.
    -- Otherwise, finding a free IP under contention might take a couple of seconds
    -- even if we do run fancy optimized window queries to find space in the table.
    free cidr UNIQUE NOT NULL PRIMARY KEY
);
INSERT INTO ip_ranges VALUES ('0.0.0.0/0'::cidr), ('::/0'::cidr);

REVOKE ALL ON TABLE ip_ranges FROM anonymous, authentication, ftp, public, stats;
GRANT ALL ON TABLE ip_ranges TO authentication;
GRANT SELECT ON TABLE ip_ranges TO stats;

CREATE OR REPLACE FUNCTION random_ip(start_addr inet, end_addr inet) RETURNS inet
    LANGUAGE SQL
    PARALLEL SAFE
    RETURNS NULL ON NULL INPUT
    RETURN start_addr + random(0, end_addr - start_addr);
    -- Returns a random IP address within the given range (inclusive)

CREATE OR REPLACE FUNCTION ip_release(addr inet) RETURNS inet AS $$
    -- Returns an IP address to the pool of free IP ranges
    DECLARE
        self   cidr;
        buddy  cidr;
        parent cidr;
    BEGIN
        IF family(addr) = 4 AND masklen(addr) != 32 THEN
            RAISE EXCEPTION 'Trying to release network %, not address', addr;
        ELSIF family(addr) = 6 AND masklen(addr) != 128 THEN
            RAISE EXCEPTION 'Trying to release network %, not address', addr;
        END IF;

        self := addr::cidr;
        FOR bits IN REVERSE masklen(addr) .. 1 LOOP
            parent := set_masklen(self, bits - 1);

            IF self = set_masklen(parent, bits) THEN
                buddy := broadcast(self) + 1;
            ELSE
                buddy := set_masklen(parent, bits);
            END IF;

            IF self != addr::cidr THEN
                -- This is the result of merging. This means that the IP actually is in the
                -- table already, and we just want to merge upwards. To make this compatible
                -- with a (possibly concurrent) allocation, delete our old entry first.
                DELETE FROM ip_ranges WHERE free = self;
                IF NOT FOUND THEN
                    -- We were already reallocated, and are done.
                    EXIT;
                END IF;
            END IF;

            -- The current address is not in the table (anymore), try to replace its buddy with
            -- the result of merging (i.e., the parent network).
            UPDATE ip_ranges SET free = parent WHERE free = buddy;
            IF NOT FOUND THEN
                -- If that doesn't work, the buddy isn't (fully) free, so just (re)insert our range.
                INSERT INTO ip_ranges VALUES (self);
                EXIT;
            END IF;

            self := parent;
        END LOOP;

        RETURN addr;
    END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ip_reserve(addr inet) RETURNS inet AS $$
    -- Removes an individual IP address from the pool of free IP ranges
    DECLARE
        split cidr;
        l     cidr;
        r     cidr;
    BEGIN
        IF family(addr) = 4 AND masklen(addr) != 32 THEN
            RAISE EXCEPTION 'Trying to allocate network %, not address', addr;
        ELSIF family(addr) = 6 AND masklen(addr) != 128 THEN
            RAISE EXCEPTION 'Trying to allocate network %, not address', addr;
        END IF;

        DELETE FROM ip_ranges
            WHERE addr <<= free
            RETURNING free
            INTO split;

        IF split IS NULL THEN
            -- This can happen if we race this with a block merge in ip_release
            -- or another allocation here. No matter, we'll retry.
            RETURN NULL;
        END IF;

        WHILE masklen(split) < masklen(addr) LOOP
            l := set_masklen(split, masklen(split) + 1);
            r := broadcast(l) + 1;
            IF addr <<= l THEN
                INSERT INTO ip_ranges VALUES (r);
                split := l;
            ELSE
                INSERT INTO ip_ranges VALUES (l);
                split := r;
            END IF;
        END LOOP;

        IF split != addr THEN
            RAISE EXCEPTION 'Sanity check: splitting blocks did not result in the original address';
        END IF;
        RETURN addr;
    END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ip_allocate_from_range(start_addr inet, end_addr inet) RETURNS inet AS $$
    -- Allocates a free IP from the given range, or returns NULL if none are available
    -- (or if the allocation raced, which should not usually happen).
    DECLARE
        ip    inet;
        block cidr;
        pivot inet;
        mask  INTEGER;
    BEGIN
        IF family(start_addr) = 4 THEN
            mask := 32;
        ELSE
            mask := 128;
        END IF;

        -- Pick an arbitrary block from the pool.
        -- Try the fast way first. This might only sample blocks from the wrong family though.
        SELECT free INTO block FROM ip_ranges
            TABLESAMPLE SYSTEM_ROWS(1000)
            WHERE (start_addr <= free OR start_addr <<= free) AND
                  (free <= end_addr OR end_addr <<= free)
            ORDER BY random()
            LIMIT 1;

        IF block IS NULL THEN
            -- This is the slower way: pick the 500 first entries from after the random pivot,
            -- then the 500 first entries from before the pivot as a backup, and pick a random
            -- one from those. It's also less random, but at least guaranteed to not hit the
            -- filter _after_ the sampling.
            pivot := random_ip(start_addr, end_addr);
            SELECT free INTO block FROM (
                (
                    SELECT free FROM ip_ranges
                        WHERE (pivot <= free OR pivot <<= free) AND
                              (free <= end_addr OR end_addr <<= free)
                        LIMIT 500
                )
                UNION ALL
                (
                    SELECT free FROM ip_ranges
                        WHERE (start_addr <= free OR start_addr <<= free) AND
                              (free < pivot OR free <<= pivot)
                        LIMIT 500
                )
            ) ORDER BY random()
              LIMIT 1;

            IF block IS NULL THEN
                RETURN NULL;
            END IF;
        END IF;

        start_addr := GREATEST(start_addr, set_masklen(block, mask));
        end_addr := LEAST(end_addr, set_masklen(broadcast(block), mask));

        -- Pick a random free IP from the block.
        ip := random_ip(start_addr, end_addr);

        -- Allocate that IP.
        RETURN ip_reserve(ip);
    END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ip_allocate_for(user_id INTEGER, start_addr inet, end_addr inet)
RETURNS inet AS $$
    -- Allocates an IP address within the given range and inserts it into the user-to-IP mapping for the
    -- given user.
    DECLARE
        allocated inet;
    BEGIN
        allocated := ip_allocate_from_range(start_addr, end_addr);
        IF allocated IS NULL THEN
            RAISE NOTICE 'Failed to allocate IP address for user %', user_id;
            RETURN NULL;
        END IF;
        INSERT INTO ips (user_id, ip) VALUES (user_id, allocated);
        RETURN allocated;
    END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION __automatically_release_ip() RETURNS trigger AS $$
    -- This simply forwards the IP address in the deleted row to ip_release
    BEGIN
        LOCK TABLE ip_ranges IN ACCESS EXCLUSIVE MODE;
        PERFORM ip_release(OLD.ip);
        RETURN OLD; -- Doesn't mean anything in AFTER DELETE anyways.
    END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER automatically_release_ip
    AFTER DELETE ON ips
    FOR EACH ROW
    EXECUTE FUNCTION __automatically_release_ip();
    -- Deleting a user from the main IP table should release the IP



-- Statistics and performance metrics

CREATE OR REPLACE VIEW stats_functions AS
    SELECT p.oid AS oid, p.proname AS proname FROM pg_catalog.pg_proc p
    INNER JOIN pg_roles r ON p.proowner = r.oid
    WHERE r.rolname = 'stats';
REVOKE ALL ON TABLE stats_functions FROM anonymous, authentication, ftp, public, stats;
GRANT SELECT ON TABLE stats_functions TO anonymous;

CREATE OR REPLACE VIEW stats_counts AS
    SELECT s.relid, s.n_live_tup FROM pg_catalog.pg_stat_all_tables s
    WHERE s.relid = 'ip_ranges'::regclass;
REVOKE ALL ON TABLE stats_counts FROM anonymous, authentication, ftp, public, stats;
GRANT SELECT ON TABLE stats_counts TO stats;

SET ROLE stats;
CREATE OR REPLACE FUNCTION stats_active_users() RETURNS INTEGER
    LANGUAGE SQL
    PARALLEL SAFE STRICT STABLE
    AS $$ SELECT count(*) FROM public.users; $$
    SECURITY DEFINER
    SET search_path = public;
    -- Returns the number of users registered with the system

CREATE OR REPLACE FUNCTION stats_ip_ranges() RETURNS INTEGER
    LANGUAGE SQL
    PARALLEL SAFE STRICT STABLE
    AS $$ SELECT s.n_live_tup FROM public.stats_counts s WHERE s.relid = 'ip_ranges'::regclass; $$
    SECURITY DEFINER
    SET search_path = public;
    -- In essence, this returns the fragmentation level of the IP address space.

CREATE OR REPLACE FUNCTION stats_dropped_packets(ident bigint) RETURNS INTEGER AS $$
    -- Return the number of dropped packets that were logged for this user
    DECLARE
        username VARCHAR;
        result INTEGER;
    BEGIN
        username := user_by_identifier(ident);
        IF username IS NULL THEN
            RETURN 0;
        END IF;
        EXECUTE format('SELECT count(*) FROM log.%I', username) INTO result;
        RETURN result;
    EXCEPTION
        WHEN undefined_table THEN
            RETURN 0;
    END;
$$ LANGUAGE plpgsql
   PARALLEL SAFE STRICT STABLE;

CREATE OR REPLACE FUNCTION stats_dropped_bytes(ident bigint) RETURNS INTEGER AS $$
    -- Return the number of dropped bytes logged for this user
    DECLARE
        username VARCHAR;
        result INTEGER;
    BEGIN
        username := user_by_identifier(ident);
        IF username IS NULL THEN
            RETURN 0;
        END IF;
        EXECUTE format('SELECT coalesce(sum(length(packet)), 0) FROM log.%I', username) INTO result;
        RETURN result;
    EXCEPTION
        WHEN undefined_table THEN
            RETURN 0;
    END;
$$ LANGUAGE plpgsql
   PARALLEL SAFE STRICT STABLE;
RESET ROLE;



-- Per-user logging

CREATE SCHEMA IF NOT EXISTS log;
GRANT USAGE ON SCHEMA log TO public;

CREATE TABLE IF NOT EXISTS log."#template" (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    time TIMESTAMP NOT NULL,
    packet BYTEA NOT NULL,
    CHECK(id > 0 AND id < 1024) -- Only log this many messages per user to avoid running out of space
);

CREATE OR REPLACE FUNCTION create_user_log(username VARCHAR) RETURNS void AS $$
    BEGIN
        EXECUTE format('CREATE TABLE IF NOT EXISTS log.%I (LIKE log."#template" INCLUDING ALL)', username);
        EXECUTE format('REVOKE ALL ON TABLE log.%I FROM anonymous, authentication, ftp, public, stats', username);
        EXECUTE format('GRANT SELECT, INSERT ON TABLE log.%I TO anonymous', username);
        EXECUTE format('GRANT SELECT ON TABLE log.%I TO authentication', username);
    END;
$$ LANGUAGE plpgsql
   SECURITY DEFINER
   SET search_path = log;
REVOKE ALL ON FUNCTION create_user_log(username VARCHAR) FROM anonymous, authentication, ftp, public, stats;
GRANT EXECUTE ON FUNCTION create_user_log(username VARCHAR) TO authentication;

CREATE OR REPLACE FUNCTION insert_user_log(username VARCHAR, packet BYTEA) RETURNS void AS $$
    BEGIN
        EXECUTE format('INSERT INTO log.%I (time, packet) VALUES (NOW(), $1)', username)
            USING packet;
    EXCEPTION
        WHEN undefined_table THEN
            RETURN;
        WHEN check_violation THEN
            RAISE NOTICE 'Log table for user % is full.', username;
    END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fetch_user_log(username VARCHAR) RETURNS SETOF log."#template" AS $$
    BEGIN
        RETURN QUERY EXECUTE format('SELECT * FROM log.%I', username);
    EXCEPTION
        WHEN undefined_table THEN
            RETURN;
    END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION __automatically_wipe_user_log() RETURNS trigger AS $$
    -- This wipes the user log of deleted users to save space. This runs as the user doing the deletion (i.e., admin).
    BEGIN
        EXECUTE format('DROP TABLE IF EXISTS log.%I', OLD.name);
        RETURN OLD; -- Doesn't mean anything in AFTER DELETE anyways.
    END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER automatically_wipe_user_log
    AFTER DELETE ON users
    FOR EACH ROW
    EXECUTE FUNCTION __automatically_wipe_user_log();
    -- Deleting a user should remove its log table to save space



-- Regular cleanup task

CREATE OR REPLACE FUNCTION __cleanup() RETURNS void AS $$
    BEGIN
        DELETE FROM users WHERE created < now() - INTERVAL '1 hour';
    END;
$$ LANGUAGE plpgsql;
REVOKE ALL ON FUNCTION __cleanup() FROM anonymous, authentication, ftp, public, stats;

SELECT cron.schedule('clean-up-old-users', '*/5 * * * *', 'SELECT __cleanup();');
SELECT cron.schedule('vacuum-tables', '1 * * * *', 'VACUUM (ANALYZE);');
SELECT cron.schedule('ip-range-stats', '*/1 * * * *', 'ANALYZE (SKIP_LOCKED TRUE) ip_ranges;');



-- We're done with the setup

REVOKE CREATE ON SCHEMA public FROM stats;
