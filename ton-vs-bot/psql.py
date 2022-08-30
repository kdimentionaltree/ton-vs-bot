import psycopg2


with open('/run/secrets/postgres_password', 'r') as f:
    password = f.read()
db_uri = f'postgres://user1:{password}@postgres:5432/tonhelp'

with psycopg2.connect(db_uri) as con:

    with con.cursor() as cur:
        cur.execute('DROP TABLE IF EXISTS flood_control')
        cur.execute('''CREATE TABLE flood_control (
                        "timestamp" timestamp NOT NULL,
                        user_id int8 NOT NULL
                    )''')
        cur.execute('CREATE INDEX flood_control_timestamp_idx ON flood_control USING btree ("timestamp")')
        cur.execute('CREATE INDEX flood_control_user_id_idx ON flood_control USING btree (user_id, "timestamp")')

        cur.execute('DROP TABLE IF EXISTS for_updating_messages')
        cur.execute('''CREATE TABLE for_updating_messages (
                        "timestamp" timestamp NOT NULL,
                        chat_id_0 int8 NOT NULL,
                        message_id_0 int8 NOT NULL,
                        chat_id_1 int8 NOT NULL,
                        message_id_1 int8 NOT NULL
                    )''')
        cur.execute('CREATE INDEX for_updating_messages_timestamp_idx '
                    'ON for_updating_messages USING btree ("timestamp")')
        cur.execute('CREATE UNIQUE INDEX for_updating_messages_chat_id_0_idx '
                    'ON for_updating_messages USING btree (chat_id_0, message_id_0)')

        cur.execute('DROP TABLE IF EXISTS history')
        cur.execute('''CREATE TABLE history (
                        "timestamp" timestamp NOT NULL,
                        "type" text NOT NULL,
                        user_id int8 NULL,
                        volunteer_id int8 NULL,
                        column_0 text NULL,
                        column_1 text NULL,
                        column_2 text NULL
                    )''')
        cur.execute('CREATE INDEX history_timestamp_idx ON history USING btree ("timestamp")')

        cur.execute('DROP TABLE IF EXISTS languages_of_users')
        cur.execute('''CREATE TABLE languages_of_users (
                        user_id int8 NOT NULL,
                        "language" varchar(5) NOT NULL,
                        CONSTRAINT languages_of_users_pk PRIMARY KEY (user_id)
                    )''')

        cur.execute('DROP TABLE IF EXISTS message_ids')
        cur.execute('''CREATE TABLE message_ids (
                        user_id int8 NOT NULL,
                        channel_message_id int8 NOT NULL,
                        group_message_id int8 NOT NULL,
                        CONSTRAINT message_ids_pk PRIMARY KEY (user_id)
                    )''')
        cur.execute('CREATE UNIQUE INDEX message_ids_group_message_id_idx '
                    'ON message_ids USING btree (group_message_id)')

        cur.execute('DROP TABLE IF EXISTS muted_users')
        cur.execute('''CREATE TABLE muted_users (
                        user_id int8 NOT NULL,
                        muted_until timestamp NULL,
                        CONSTRAINT muted_users_pk PRIMARY KEY (user_id)
                    )''')

        cur.execute('DROP TABLE IF EXISTS open_users')
        cur.execute('''CREATE TABLE open_users (
                        user_id int8 NOT NULL,
                        opening_time timestamp NOT NULL,
                        volunteer_id int8 NULL,
                        time_of_last_message_by_user timestamp NULL,
                        time_of_last_message_by_volunteers timestamp NULL,
                        subject json NULL,
                        CONSTRAINT open_users_pk PRIMARY KEY (user_id)
                    )''')
        cur.execute('CREATE INDEX open_users_volunteer_id_idx '
                    'ON open_users USING btree (volunteer_id)')

        cur.execute('DROP TABLE IF EXISTS updates')
        cur.execute('''CREATE TABLE updates (
                        update_id int8 NOT NULL,
                        "timestamp" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        passed bool NOT NULL DEFAULT false,
                        "update" text NOT NULL,
                        CONSTRAINT updates_pk PRIMARY KEY (update_id)
                    )''')
        cur.execute('CREATE UNIQUE INDEX updates_timestamp_idx ON updates USING btree ("timestamp")')

        # cur.execute('')

        con.commit()
