#!/usr/bin/env python3

import datetime
import json
import os
import random
import re
import traceback
from time import sleep, time

import psycopg2
import telegram

from constants import *
from psql import init_database
from speaking import *
from subjects import *

SHIT_COUNTER = 0
CURRENT_UPDATE_ID = 0
BOT = None
CON = None
CUR = None
MAP_OF_CHANNEL_MESSAGE_ID_AND_USER_ID = {}
QUEUE_OF_MESSAGES_DICT = {}
QUEUE_OF_EDITED_MESSAGES_DICT = {}
LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT = {}
LAST_TIME_OF_MESSAGE_FROM_BOT_TO_CHAT_DICT = {}
LAST_TIME_OF_GREETING_MESSAGE_DICT = {}
LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT = {}
separator = '\n\n' + '-' * 64 + '\n\n'


def gaga():
    global SHIT_COUNTER

    while True:
        try:
            main()
            sleep(3)
        except:
            shit_message = f'SHIT...\n' \
                           f'SHIT_COUNTER: {SHIT_COUNTER}\n' \
                           f'time: {datetime.datetime.utcnow()}\n' \
                           f'\n' \
                           f'{traceback.format_exc()}'
            print(shit_message + separator)
            sleep(2 ** SHIT_COUNTER)
            SHIT_COUNTER += 1


def main():
    start_message = f'start {datetime.datetime.utcnow()}'

    if SHIT_COUNTER:
        start_message += f'\n\nSHIT_COUNTER: {SHIT_COUNTER}'

    print(start_message + separator)

    global BOT
    global CON
    global CUR

    try:
        # init postgres
        with open('/run/secrets/postgres_password', 'r') as f:
            password = f.read()
        db_uri = f'postgres://user1:{password}@postgres:5432/tonhelp'
        init_database(db_uri, drop_if_exists=False)

        # init bot
        with open('/run/secrets/telegram_token', 'r') as f:
            bot_token = f.read()
        BOT = telegram.Bot(bot_token)
        tg_delay(log_chat_id)
        BOT.send_message(log_chat_id, start_message, disable_notification=True)
        
        with psycopg2.connect(db_uri) as CON:
            with CON.cursor() as CUR:
                while True:
                    run()
    except:
        my_traceback(1)


def run():
    global CURRENT_UPDATE_ID
    update = None

    try:
        try:
            updates = BOT.get_updates(offset=CURRENT_UPDATE_ID, timeout=60)
        except (telegram.error.TimedOut, telegram.error.Conflict) as exc:
            minor_error(exc)
            return

        for update in updates:
            if not CURRENT_UPDATE_ID:
                CURRENT_UPDATE_ID = update.update_id

            handle_update(update)

            CURRENT_UPDATE_ID = update.update_id + 1

        cleaning()

    except telegram.error.RetryAfter as exc:
        retry_after_message = f'sleep {exc.retry_after} seconds, because telegram.error.RetryAfter'
        print(retry_after_message + separator)
        sleep(exc.retry_after)
        my_traceback(2, 'telegram.error.RetryAfter')

    except psycopg2.Error:
        CON.rollback()

        my_traceback(2, 'psycopg2.Error', update)
        CURRENT_UPDATE_ID += 1

    except:
        my_traceback(2, None, update)
        CURRENT_UPDATE_ID += 1


def handle_update(update):
    if update.message:
        message = update.message
        user = message.from_user
    elif update.edited_message:
        message = update.edited_message
        user = message.from_user
    elif update.callback_query:
        message = update.callback_query.message
        user = update.callback_query.from_user
    elif update.channel_post or update.edited_channel_post:
        if update.channel_post:
            channel_post = update.channel_post
        elif update.edited_channel_post:
            channel_post = update.edited_channel_post
        else:
            assert False

        if channel_post.chat.id == channel_chat_id or channel_post.chat.id in subjects_channels.values():
            pass
        else:
            log_mgs = f'Leaving channel: {channel_post.chat.id}'
            BOT.send_message(log_chat_id, log_mgs, disable_notification=True)
            BOT.leave_chat(channel_post.chat.id)
        return
    else:
        return

    if not mute_control(user):
        return

    if not flood_control(update):
        return

    if message.chat.id < 0 and message.chat.id not in {channel_chat_id, group_chat_id, log_chat_id}:
        if not message.left_chat_member:
            log_mgs = f'Leaving channel: {message.chat.id}'
            BOT.send_message(log_chat_id, log_mgs, disable_notification=True)
            BOT.leave_chat(message.chat.id)
        return

    CUR.execute(
        'SELECT 1 FROM updates WHERE update_id = %s',
        (update.update_id,)
    )
    query_result = CUR.fetchone()

    if not query_result:
        CUR.execute(
            'INSERT INTO updates (update_id, "update") VALUES (%s, %s)',
            (update.update_id, str(update))
        )
        CON.commit()

    if update.message:
        if message.from_user.id == 777000 and message.sender_chat.id == channel_chat_id:
            message_from_channel(message)

        elif message.chat.id == group_chat_id:
            message_in_group(message)

        elif message.chat.id > 0:
            private_message(message)

    elif update.edited_message:
        handle_edited_message(message)

    elif update.callback_query:
        handle_callback_query(update)

    CUR.execute(
        'UPDATE updates SET passed = true WHERE update_id = %s',
        (update.update_id,)
    )
    CON.commit()


def mute_control(tg_user):
    CUR.execute(
        'SELECT muted_until FROM muted_users WHERE user_id = %s',
        (tg_user.id,)
    )
    query_result = CUR.fetchone()

    if query_result:
        muted_until = query_result[0]

        if muted_until:
            if datetime.datetime.utcnow() > muted_until:
                CUR.execute(
                    'DELETE FROM muted_users WHERE user_id = %s',
                    (tg_user.id,)
                )
                CON.commit()

                update_channel_posts(tg_user)

                return True
            else:
                return False
        else:
            return False
    else:
        return True


def flood_control(update):
    def count(user_id, date, seconds):
        CUR.execute(
            ''' 
                select
                    count(*)
                from
                    flood_control
                where 
                    user_id = %s
                    and "timestamp" < %s 
                    and "timestamp" > %s
            ''',
            (
                user_id,
                date,
                date - datetime.timedelta(seconds=seconds)
            )
        )
        query_result = CUR.fetchone()
        return query_result[0]

    def caution(message, date, reason):
        def send_caution(date):
            add_to_history(
                timestamp=date,
                type='bot_action',
                user_id=message.from_user.id,
                volunteer_id=None,
                column_0='flood_control_caution',
                column_1=reason,
                column_2=None
            )

            date = date.replace(tzinfo=None)

            report_message = 'flood control\n' \
                             'user caution\n' \
                             '\n' \
                             'user_id: {}\n' \
                             'reason: {}\n' \
                             'message time: {}\n' \
                             'bot time: {}'.format(
                message.from_user.id,
                reason,
                date,
                datetime.datetime.utcnow()
            )

            tg_delay(log_chat_id)
            BOT.send_message(log_chat_id, report_message)

            CUR.execute(
                'SELECT group_message_id FROM message_ids WHERE user_id = %s',
                (message.from_user.id,)
            )
            query_result = CUR.fetchone()

            if query_result:
                group_message_id = query_result[0]

                message_to_comments = '`❗ Flood control. Caution. {}`'.format(reason)

                tg_delay(group_chat_id)
                BOT.send_message(
                    group_chat_id,
                    message_to_comments,
                    reply_to_message_id=group_message_id,
                    allow_sending_without_reply=True,
                    parse_mode='MarkdownV2'
                )

            speaking('flood_control_caution', message, reply=True, mono=True)
            LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT[message.from_user.id] = time()

        if message.from_user.id in LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT:
            time_value = 60 * 5

            if time() - LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT[message.from_user.id] > time_value:
                send_caution(date)
        else:
            send_caution(date)

    def mute(message, date, reason):
        CUR.execute(
            'INSERT INTO muted_users (user_id) VALUES (%s)',
            (message.from_user.id,)
        )
        CON.commit()

        add_to_history(
            timestamp=date,
            type='bot_action',
            user_id=message.from_user.id,
            volunteer_id=None,
            column_0='mute_user',
            column_1='flood_control',
            column_2=reason
        )

        date = date.replace(tzinfo=None)

        report_message = f'flood control\n' \
                         f'mute user\n' \
                         f'\n' \
                         f'user_id: {message.from_user.id}\n' \
                         f'reason: {reason}\n' \
                         f'message time: {date}\n' \
                         f'bot time: {datetime.datetime.utcnow()}'

        tg_delay(log_chat_id)
        BOT.send_message(log_chat_id, report_message)

        update_channel_posts(message.from_user)

        CUR.execute(
            'SELECT group_message_id FROM message_ids WHERE user_id = %s',
            (message.from_user.id,)
        )
        query_result = CUR.fetchone()

        if query_result:
            group_message_id = query_result[0]

            message_to_comments = '`❗ Flood control. {}. User was muted forever`'.format(reason)

            tg_delay(group_chat_id)
            BOT.send_message(
                group_chat_id,
                message_to_comments,
                reply_to_message_id=group_message_id,
                allow_sending_without_reply=True,
                parse_mode='MarkdownV2'
            )

        speaking('flood_control_mute', message, reply=True, mono=True)

    ################

    if update.message:
        message = update.message
        date = update.message.date
    elif update.edited_message:
        message = update.edited_message
        date = update.edited_message.edit_date
    elif update.callback_query:
        return True
    else:
        assert False

    if message.from_user.id == 777000:
        return True

    count_of_60_sec = count(message.from_user.id, date, 60)
    if count_of_60_sec > 20:
        mute(message, date, '> 20 messages per 60 sec')
        return False
    elif count_of_60_sec > 13:
        caution(message, date, '> 13 messages per 60 sec')

    count_of_3600_sec = count(message.from_user.id, date, 3600)
    if count_of_3600_sec > 300:
        mute(message, date, '> 300 messages per 3600 sec')
        return False
    elif count_of_3600_sec > 200:
        caution(message, date, '> 200 messages per 3600 sec')

    count_of_86400_sec = count(message.from_user.id, date, 86400)
    if count_of_86400_sec > 1000:
        mute(message, date, '> 1000 messages per 86400 sec')
        return False
    elif count_of_86400_sec > 900:
        caution(message, date, '> 900 messages per 86400 sec')

    CUR.execute(
        'INSERT INTO flood_control ("timestamp", user_id) VALUES (%s, %s)',
        (date, message.from_user.id)
    )
    CON.commit()

    return True


def message_from_channel(message):
    if message.forward_from_message_id in MAP_OF_CHANNEL_MESSAGE_ID_AND_USER_ID:
        user_id = MAP_OF_CHANNEL_MESSAGE_ID_AND_USER_ID[message.forward_from_message_id]

        CUR.execute(
            'INSERT INTO message_ids (user_id, channel_message_id, group_message_id) VALUES (%s, %s, %s)',
            (
                user_id,
                message.forward_from_message_id,
                message.message_id
            )
        )
        CON.commit()

        queue_of_messages_list = QUEUE_OF_MESSAGES_DICT[user_id].copy()
        queue_of_edited_messages_list = QUEUE_OF_EDITED_MESSAGES_DICT[user_id].copy()

        del QUEUE_OF_EDITED_MESSAGES_DICT[user_id]
        del QUEUE_OF_MESSAGES_DICT[user_id]
        del MAP_OF_CHANNEL_MESSAGE_ID_AND_USER_ID[message.forward_from_message_id]

        for message_from_queue in queue_of_messages_list:
            if message_from_queue.__class__.__name__ == 'NotFirstChannelPostMarker':
                tg_delay(group_chat_id)
                BOT.send_message(
                    group_chat_id,
                    '`ℹ replied message not found, created new channel post`',
                    reply_to_message_id=message.message_id,
                    allow_sending_without_reply=True,
                    parse_mode='MarkdownV2'
                )
                continue

            my_forward_message(group_chat_id, message_from_queue, message.message_id)

        for edited_message_from_queue in queue_of_edited_messages_list:
            handle_edited_message(edited_message_from_queue)

        update_channel_posts(user_id, {channel_chat_id})


def message_in_group(message):
    if message.reply_to_message:
        if (message.text and len(message.text) >= 2 and message.text[0:2] in ['//', '\\\\']) \
                or \
                (message.reply_to_message.text and len(message.reply_to_message.text) >= 2
                 and message.reply_to_message.text[0:2] in ['//', '\\\\']):
            return

        if message.text == '/del':
            # add_to_history troubles

            CommandsInGroup.delete_message(message)
            return

        if message.reply_to_message.from_user.id == 777000:
            message_id = message.reply_to_message.message_id

            CUR.execute(
                'SELECT user_id FROM message_ids WHERE group_message_id = %s',
                (message_id,)
            )
            query_result = CUR.fetchone()

            if query_result:
                user_id = query_result[0]

                if message.text and message.text[0] == '/':
                    command_in_group(message, user_id)
                    return

                my_forward_message(user_id, message)

                CUR.execute(
                    'UPDATE open_users SET time_of_last_message_by_volunteers = %s WHERE user_id = %s',
                    (message.date, user_id)
                )
                CON.commit()

            else:
                speaking('channel_post_is_inactive', message, reply=True, mono=True, eng=True)

        else:
            speaking('dont_use_reply_in_comments', message, reply=True, mono=True, eng=True)

    else:
        speaking('dont_send_messages_outside_comments', message, reply=True, mono=True, eng=True)


def private_message(message):
    if message.text and message.text[0] == '/':
        command_in_pm(message)
        return

    if message.from_user.id in QUEUE_OF_MESSAGES_DICT:
        QUEUE_OF_MESSAGES_DICT[message.from_user.id].append(message)
        return

    #

    CUR.execute(
        'SELECT group_message_id FROM message_ids WHERE user_id = %s',
        (message.from_user.id,)
    )
    message_ids_query_result = CUR.fetchone()

    # user open status

    CUR.execute(
        'SELECT 1 FROM open_users WHERE user_id = %s',
        (message.from_user.id,)
    )
    query_result = CUR.fetchone()

    if not query_result:
        CUR.execute(
            'INSERT INTO open_users (user_id, opening_time) VALUES (%s, %s)',
            (message.from_user.id, message.date)
        )
        CON.commit()

        add_to_history(
            timestamp=message.date,
            type='bot_action',
            user_id=message.from_user.id,
            volunteer_id=None,
            column_0='open_user',
            column_1=None,
            column_2=None
        )

        if message_ids_query_result:
            group_message_id = message_ids_query_result[0]

            tg_delay(group_chat_id)
            sent_message = BOT.send_message(
                group_chat_id,
                '`🙋 user just opened`',
                reply_to_message_id=group_message_id,
                allow_sending_without_reply=True,
                parse_mode='MarkdownV2'
            )

            opening_message_id = sent_message.message_id
        else:
            opening_message_id = None

        update_channel_posts(message.from_user)

        if message.from_user.id in LAST_TIME_OF_GREETING_MESSAGE_DICT:
            time_value = 86400

            if time() - LAST_TIME_OF_GREETING_MESSAGE_DICT[message.from_user.id] > time_value:
                CommandsInPM.start(message)
        else:
            CommandsInPM.start(message)
        LAST_TIME_OF_GREETING_MESSAGE_DICT[message.from_user.id] = time()

        tg_delay(subjects_channels[''])
        sent_message = BOT.send_message(
            subjects_channels[''],
            channel_post_text(message.from_user, mode=1),
            parse_mode='MarkdownV2'
        )

        subject_cell = {
            'opening_message_id': opening_message_id,
            'menu_message_id': None,
            'subject_path': '',
            'posts_in_subject_channels': {
                subjects_channels['']: sent_message.message_id
            }
        }

        CUR.execute(
            'UPDATE open_users SET subject = %s WHERE user_id = %s',
            (json.dumps(subject_cell), message.from_user.id)
        )
        CON.commit()

    # end of user open status

    # other

    CUR.execute(
        'UPDATE open_users SET time_of_last_message_by_user = %s WHERE user_id = %s',
        (message.date, message.from_user.id)
    )
    CON.commit()

    #

    if message_ids_query_result:
        group_message_id = message_ids_query_result[0]
        my_forward_message(group_chat_id, message, group_message_id)
    else:
        create_channel_post(message)


def handle_edited_message(edited_message):
    if edited_message.chat.id in QUEUE_OF_EDITED_MESSAGES_DICT:
        QUEUE_OF_EDITED_MESSAGES_DICT[edited_message.chat.id].append(edited_message)
        return

    CUR.execute(
        'SELECT chat_id_1, message_id_1 FROM for_updating_messages WHERE chat_id_0 = %s AND message_id_0 = %s',
        (edited_message.chat.id, edited_message.message_id)
    )
    query_result = CUR.fetchone()

    if query_result:
        try:
            chat_id_1 = query_result[0]
            message_id_1 = query_result[1]

            tg_delay(chat_id_1)

            # stickers and video_notes - not editable
            # voices - editable only caption
            if edited_message.text:
                BOT.edit_message_text(
                    edited_message.text,
                    chat_id_1,
                    message_id_1,
                    entities=edited_message.entities
                )
                # history_column_1 = 'text'
                # history_column_2 = edited_message.text
            elif edited_message.photo:
                file_id = edited_message.photo[-1].file_id
                BOT.edit_message_media(
                    chat_id_1,
                    message_id_1,
                    media=telegram.InputMediaPhoto(
                        file_id,
                        caption=edited_message.caption,
                        caption_entities=edited_message.caption_entities
                    )
                )
                # history_column_1 = 'photo'
                # history_column_2 = f'{file_id}\n{edited_message.caption}'
            elif edited_message.video:
                file_id = edited_message.video.file_id
                BOT.edit_message_media(
                    chat_id_1,
                    message_id_1,
                    media=telegram.InputMediaVideo(
                        file_id,
                        caption=edited_message.caption,
                        caption_entities=edited_message.caption_entities
                    )
                )
                # history_column_1 = 'video'
                # history_column_2 = f'{file_id}\n{edited_message.caption}'
            elif edited_message.audio:
                file_id = edited_message.audio.file_id
                BOT.edit_message_media(
                    chat_id_1,
                    message_id_1,
                    media=telegram.InputMediaAudio(
                        file_id,
                        caption=edited_message.caption,
                        caption_entities=edited_message.caption_entities
                    )
                )
                # history_column_1 = 'audio'
                # history_column_2 = f'{file_id}\n{edited_message.caption}'
            elif edited_message.voice:
                BOT.edit_message_caption(
                    chat_id_1,
                    message_id_1,
                    caption=edited_message.caption,
                    caption_entities=edited_message.caption_entities
                )
                # history_column_1 = 'voice'
                # history_column_2 = edited_message.caption
            elif edited_message.animation:
                file_id = edited_message.animation.file_id
                BOT.edit_message_media(
                    chat_id_1,
                    message_id_1,
                    media=telegram.InputMediaAnimation(
                        file_id,
                        caption=edited_message.caption,
                        caption_entities=edited_message.caption_entities
                    )
                )
                # history_column_1 = 'animation'
                # history_column_2 = f'{file_id}\n{edited_message.caption}'
            elif edited_message.document:
                file_id = edited_message.document.file_id
                BOT.edit_message_media(
                    chat_id_1,
                    message_id_1,
                    media=telegram.InputMediaDocument(
                        file_id,
                        caption=edited_message.caption,
                        caption_entities=edited_message.caption_entities
                    )
                )
                # history_column_1 = 'document'
                # history_column_2 = f'{file_id}\n{edited_message.caption}'
            else:
                report = f'info\n' \
                         f'\n' \
                         f'unsupported message type in handling edited message\n' \
                         f'\n' \
                         f'{str(edited_message)}'

                print(report + separator)

                tg_delay(log_chat_id)
                BOT.send_message(log_chat_id, truncate_big_text(0, report))

                return

            history_column_1, history_column_2 = get_column_1_and_column_2(edited_message)

            if edited_message.chat.id == group_chat_id:
                user_id = chat_id_1
                volunteer_id = edited_message.from_user.id
                history_column_0 = edited_message.message_id
            elif edited_message.chat.id > 0:
                user_id = edited_message.from_user.id
                volunteer_id = None
                history_column_0 = message_id_1
            else:
                assert False

            add_to_history(
                timestamp=edited_message.edit_date,
                type='edited_message',
                user_id=user_id,
                volunteer_id=volunteer_id,
                column_0=history_column_0,
                column_1=history_column_1,
                column_2=history_column_2
            )

        except telegram.error.BadRequest as exc:
            error_0_text = 'Message is not modified: ' \
                           'specified new message content and reply markup are exactly the same ' \
                           'as a current content and reply markup of the message'
            error_1_text = 'Message_id_invalid'
            error_2_text = 'Message to edit not found'

            if str(exc) in {error_0_text, error_1_text, error_2_text}:
                pass
            else:
                raise exc


def handle_callback_query(update):
    try:
        callback_query = update.callback_query
        data = callback_query.data

        if not any((
                data.startswith('subject:'),
                data.startswith('close:'),
        )):
            return

        add_to_history(
            timestamp=datetime.datetime.utcnow(),
            type='callback_query',
            user_id=callback_query.from_user.id,
            volunteer_id=None,
            column_0=callback_query.id,
            column_1=callback_query.data,
            column_2=None
        )

        if data.startswith('subject:') or data.startswith('close:'):
            subject_callback(update)
            return

    except telegram.error.BadRequest as exc:
        if str(exc) == 'Query is too old and response timeout expired or query id is invalid':
            report = f'info\n' \
                     f'\n' \
                     f'{str(exc)}' \
                     f'\n' \
                     f'callback_query.id: {update.callback_query.id}\n'

            print(report + separator)

            tg_delay(log_chat_id)
            BOT.send_message(log_chat_id, report)
        else:
            raise exc


def command_in_pm(message):
    text = message.text

    add_to_history(
        timestamp=message.date,
        type='message',
        user_id=message.from_user.id,
        volunteer_id=None,
        column_0=None,
        column_1='text',
        column_2=message.text
    )

    if message.from_user.id == DG_user_id:
        DG_commands(message)

    if text == '/start':
        CommandsInPM.start(message)
        return

    # elif bool(re.match('/lang.*', text)):
    #     CommandsInPM.lang(message)
    #     return

    if text in {'/l', '/list', '/t', '/taken'}:
        volunteers_commands_in_pm(message)
        return


def volunteers_commands_in_pm(message):
    text = message.text

    if is_volunteer(message.from_user):
        if text in {'/l', '/list'}:
            CommandsInPM.list(message)
            return

        elif text in {'/t', '/taken'}:
            CommandsInPM.taken(message)
            return


class CommandsInPM:
    @staticmethod
    def start(message):
        speaking('greeting_message', message, markdown=True)
        LAST_TIME_OF_GREETING_MESSAGE_DICT[message.from_user.id] = time()

    @staticmethod
    def lang(message):
        text = message.text

        split = re.split('_+', text)

        if len(split) == 1:
            speaking('lang_command', message, reply=True, cut_big_text=True)

        elif len(split) == 2 and split[0] == '/lang' and split[1] in languages_dict:
            enter_lang = split[1]

            if enter_lang != get_user_language(message):

                CUR.execute(
                    'UPDATE languages_of_users SET "language" = %s WHERE user_id = %s',
                    (enter_lang, message.from_user.id)
                )
                CON.commit()

                update_channel_posts(message.from_user)

                speaking('language_was_changed', message, reply=True, mono=True)

                speaking('greeting_message', message, markdown=True)

                LAST_TIME_OF_GREETING_MESSAGE_DICT[message.from_user.id] = time()

            else:
                speaking('you_enter_the_same_language', message, reply=True, mono=True)

        else:
            speaking('bad_entered_command', message, reply=True, mono=True)

    @staticmethod
    def list(message):
        CUR.execute(
            '''
                select
                    ou.volunteer_id,
                    ou.user_id,
                    lou."language",
                    ou.opening_time,
                    ou.time_of_last_message_by_user,
                    ou.time_of_last_message_by_volunteers,
                    mi.channel_message_id
                from
                    open_users ou
                left join languages_of_users lou
                on
                    ou.user_id = lou.user_id
                left join message_ids mi 
                on
                    ou.user_id = mi.user_id
                order by
                    ou.volunteer_id is null desc,
                    opening_time
            '''
        )
        query_result = CUR.fetchall()

        response_text = 'list of open users \({}\)'.format(len(query_result))

        for row in query_result:
            volunteer_id = row[0]
            user_id = row[1]
            user_language = row[2]
            opening_time = row[3]
            time_of_last_message_by_user = row[4]
            time_of_last_message_by_volunteers = row[5]
            channel_message_id = row[6]

            text_opening_time = str(datetime.datetime.utcnow().replace(microsecond=0) - opening_time)

            if time_of_last_message_by_user:
                text_time_of_last_message_by_user = str(datetime.datetime.utcnow().replace(microsecond=0)
                                                        - time_of_last_message_by_user)

            else:
                text_time_of_last_message_by_user = 'no messages'

            if time_of_last_message_by_volunteers:
                text_time_of_last_message_by_volunteers = str(datetime.datetime.utcnow().replace(microsecond=0)
                                                              - time_of_last_message_by_volunteers)
            else:
                text_time_of_last_message_by_volunteers = 'no answer'

            candidate_to_response_text = '\n' \
                                         '\n' \
                                         '{} {}\n' \
                                         '    {}\n' \
                                         '        {}\n' \
                                         '            {}\n' \
                                         '                {}\n' \
                                         '                    {}'.format(
                '🟡' if volunteer_id else '🔴',
                escape_markdown(get_tg_user_info(user_id)),
                user_language,
                text_opening_time,
                text_time_of_last_message_by_user,
                text_time_of_last_message_by_volunteers,
                f'[link to post]({channel_link}/{channel_message_id})'
            )

            if len(response_text + candidate_to_response_text) > 4096:
                break
            else:
                response_text += candidate_to_response_text

        if len(query_result) == 0:
            response_text += '\n\nempty'

        tg_delay(message.from_user.id)
        BOT.send_message(
            message.from_user.id,
            response_text,
            reply_to_message_id=message.message_id,
            allow_sending_without_reply=True,
            parse_mode='MarkdownV2'
        )

    @staticmethod
    def taken(message):
        CUR.execute(
            '''
                select
                    ou.user_id,
                    lou."language",
                    ou.opening_time, 
                    ou.time_of_last_message_by_user,
                    ou.time_of_last_message_by_volunteers,
                    mi.channel_message_id
                from
                    open_users ou
                left join languages_of_users lou
                on
                    ou.user_id = lou.user_id
                left join message_ids mi 
                on
                    ou.user_id = mi.user_id
                where
                    ou.volunteer_id = %s
                order by
                    ou.opening_time
            ''',
            (message.from_user.id,)
        )
        query_result = CUR.fetchall()

        response_text = 'list of taken users by you \({}\)'.format(len(query_result))

        for row in query_result:
            user_id = row[0]
            language = row[1]
            opening_time = row[2]
            time_of_last_message_by_user = row[3]
            time_of_last_message_by_volunteers = row[4]
            channel_message_id = row[5]

            text_opening_time = str(datetime.datetime.utcnow().replace(microsecond=0) - opening_time)

            if time_of_last_message_by_user:
                text_time_of_last_message_by_user = str(datetime.datetime.utcnow().replace(microsecond=0)
                                                        - time_of_last_message_by_user)
            else:
                text_time_of_last_message_by_user = 'no message'

            if time_of_last_message_by_volunteers:
                text_time_of_last_message_by_volunteers = str(datetime.datetime.utcnow().replace(microsecond=0)
                                                              - time_of_last_message_by_volunteers)
            else:
                text_time_of_last_message_by_volunteers = 'no answer'

            candidate_to_response_text = '\n' \
                                         '\n' \
                                         '• {}\n' \
                                         '    {}\n' \
                                         '        {}\n' \
                                         '            {}\n' \
                                         '                {}\n' \
                                         '                    {}'.format(
                escape_markdown(get_tg_user_info(user_id)),
                language,
                text_opening_time,
                text_time_of_last_message_by_user,
                text_time_of_last_message_by_volunteers,
                '[link to post]({}/{})'.format(channel_link, channel_message_id)
            )

            if len(response_text + candidate_to_response_text) > 4096:
                break
            else:
                response_text += candidate_to_response_text

        if len(query_result) == 0:
            response_text += '\n\nempty'

        tg_delay(message.from_user.id)
        BOT.send_message(
            message.from_user.id,
            response_text,
            reply_to_message_id=message.message_id,
            allow_sending_without_reply=True,
            parse_mode='MarkdownV2'
        )


def DG_commands(message):
    text = message.text

    if text == '/help':
        DgCommands.help()
        return

    elif text == '/get_shit_counter':
        DgCommands.get_shit_counter()
        return

    elif text == '/reset_shit_counter':
        DgCommands.reset_shit_counter()
        return

    elif text == '/gaga':
        DgCommands.gaga()
        return

    elif bool(re.match('/tables_counts.*', text)):
        DgCommands.tables_counts(message)
        return


class DgCommands:
    @staticmethod
    def help():
        help_text = '/help\n' \
                    '/gaga\n' \
                    '/get_shit_counter\n' \
                    '/reset_shit_counter\n' \
                    '/tables_counts # 1 day\n' \
                    '/tables_counts n # n - days\n'

        tg_delay(DG_user_id)
        BOT.send_message(DG_user_id, truncate_big_text(0, help_text))

    @staticmethod
    def get_shit_counter():
        tg_delay(DG_user_id)
        BOT.send_message(DG_user_id, f'SHIT_COUNTER: {SHIT_COUNTER}')

    @staticmethod
    def reset_shit_counter():
        global SHIT_COUNTER
        SHIT_COUNTER = 0

        tg_delay(DG_user_id)
        BOT.send_message(DG_user_id, 'mb ok')

    @staticmethod
    def gaga():
        CUR.execute('SELECT COUNT(*) FROM updates WHERE passed = false')
        query_result = CUR.fetchone()
        if query_result:
            problem_updates_count = query_result[0]
        else:
            problem_updates_count = None

        gaga_text = f'SHIT_COUNTER: {SHIT_COUNTER}\n' \
                    f'problem_updates_count (n - 1): {problem_updates_count}\n' \
                    f'\n' \
                    f'len(MAP_OF_CHANNEL_MESSAGE_ID_AND_USER_ID): {len(MAP_OF_CHANNEL_MESSAGE_ID_AND_USER_ID)}\n' \
                    f'len(QUEUE_OF_MESSAGES_DICT): {len(QUEUE_OF_MESSAGES_DICT)}\n' \
                    f'len(QUEUE_OF_EDITED_MESSAGES_DICT): {len(QUEUE_OF_EDITED_MESSAGES_DICT)}\n' \
                    f'\n' \
                    f'len(LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT): {len(LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT)}\n' \
                    f'len(LAST_TIME_OF_GREETING_MESSAGE_DICT): {len(LAST_TIME_OF_GREETING_MESSAGE_DICT)}\n' \
                    f'len(LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT): {len(LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT)}\n'

        tg_delay(DG_user_id)
        BOT.send_message(DG_user_id, gaga_text)

    @staticmethod
    def tables_counts(message):
        def gaga(days):
            dt = datetime.datetime.utcnow() - datetime.timedelta(days=days)

            CUR.execute('SELECT COUNT(*) FROM flood_control WHERE "timestamp" > %s', (dt,))
            query_result = CUR.fetchone()
            if query_result:
                flood_control_count = query_result[0]
            else:
                flood_control_count = None

            CUR.execute('SELECT COUNT(*) FROM history WHERE "timestamp" > %s', (dt,))
            query_result = CUR.fetchone()
            if query_result:
                history_count = query_result[0]
            else:
                history_count = None

            CUR.execute('SELECT COUNT(*) FROM updates WHERE "timestamp" > %s', (dt,))
            query_result = CUR.fetchone()
            if query_result:
                updates_count = query_result[0]
            else:
                updates_count = None

            report_message = f'days: {days}\n' \
                             f'\n' \
                             f'flood_control_count: {flood_control_count}\n' \
                             f'history_count: {history_count}\n' \
                             f'updates_count: {updates_count}'

            tg_delay(DG_user_id)
            BOT.send_message(DG_user_id, report_message)

        ####

        split = re.split(' +', message.text)

        if len(split) == 1:
            gaga(1)
        elif len(split) == 2 and split[1].isdigit():
            number_of_days = int(split[1])
            gaga(number_of_days)
        else:
            speaking('bad_entered_command', message, reply=True, mono=True, eng=True)


def command_in_group(message, user_id):
    text = message.text

    add_to_history(
        timestamp=message.date,
        type='message',
        user_id=user_id,
        volunteer_id=message.from_user.id,
        column_0=message.message_id,
        column_1='text',
        column_2=message.text
    )

    if text in {'/t', '/take'}:
        CommandsInGroup.take(message, user_id)
        return

    elif text in {'/d', '/drop'}:
        CommandsInGroup.drop(message, user_id)
        return

    elif text in {'/c', '/close'}:
        CommandsInGroup.subject_or_close('close', message, user_id)
        return

    elif text in {'/o', '/open'}:
        CommandsInGroup.open(message, user_id)
        return

    # elif bool(re.match('/mute.*', text)):
    elif text.startswith('/mute'):
        CommandsInGroup.mute(message, user_id)
        return

    elif text == '/unmute':
        CommandsInGroup.unmute(message, user_id)
        return

    elif text in {'/s', '/subject'}:
        CommandsInGroup.subject_or_close('subject', message, user_id)
        return

    else:
        speaking('I_dont_know_this_command', message, reply=True, mono=True, eng=True)


class CommandsInGroup:
    @staticmethod
    def take(message, user_id):
        CUR.execute(
            'SELECT volunteer_id FROM open_users WHERE user_id = %s',
            (user_id,)
        )
        query_result = CUR.fetchone()

        if query_result:
            volunteer_id = query_result[0]

            if not volunteer_id:
                CUR.execute(
                    'UPDATE open_users SET volunteer_id = %s WHERE user_id = %s',
                    (message.from_user.id, user_id)
                )
                CON.commit()

                add_to_history(
                    timestamp=message.date,
                    type='bot_action',
                    user_id=user_id,
                    volunteer_id=message.from_user.id,
                    column_0='take_user',
                    column_1=None,
                    column_2=None
                )

                speaking('you_have_taken_this_user', message, reply=True, mono=True, eng=True)

                update_channel_posts(user_id)

            else:
                if message.from_user.id == volunteer_id:
                    speaking('this_user_is_already_taken_by_you', message, reply=True, mono=True, eng=True)
                else:
                    speaking('this_user_is_already_taken', message, reply=True, mono=True, eng=True)
        else:
            speaking('this_user_is_not_open', message, reply=True, mono=True, eng=True)

    @staticmethod
    def drop(message, user_id):
        CUR.execute(
            'SELECT volunteer_id FROM open_users WHERE user_id = %s',
            (user_id,)
        )
        query_result = CUR.fetchone()

        if query_result:
            volunteer_id = query_result[0]

            if message.from_user.id == volunteer_id:
                CUR.execute(
                    'UPDATE open_users SET volunteer_id = NULL WHERE user_id = %s',
                    (user_id,)
                )
                CON.commit()

                add_to_history(
                    timestamp=message.date,
                    type='bot_action',
                    user_id=user_id,
                    volunteer_id=message.from_user.id,
                    column_0='drop_user',
                    column_1=None,
                    column_2=None
                )

                speaking('you_have_dropped_this_user', message, reply=True, mono=True, eng=True)

                update_channel_posts(user_id)

            else:
                speaking('this_user_is_not_taken_by_you', message, reply=True, mono=True, eng=True)

        else:
            speaking('this_user_is_not_open', message, reply=True, mono=True, eng=True)

    @staticmethod
    def open(message, user_id):
        CUR.execute(
            'SELECT 1 FROM open_users WHERE user_id = %s',
            (user_id,)
        )
        query_result = CUR.fetchone()

        if not query_result:
            CUR.execute(
                'INSERT INTO open_users (user_id, opening_time) VALUES (%s, %s)',
                (user_id, message.date)
            )
            CON.commit()

            add_to_history(
                timestamp=message.date,
                type='bot_action',
                user_id=user_id,
                volunteer_id=message.from_user.id,
                column_0='open_user',
                column_1=None,
                column_2=None
            )

            opening_message_id = speaking('user_have_been_opened', message, reply=True, mono=True, eng=True,
                                          return_message_id=True)

            update_channel_posts(user_id)

            tg_delay(subjects_channels[''])
            sent_message = BOT.send_message(
                subjects_channels[''],
                channel_post_text(user_id, mode=1),
                parse_mode='MarkdownV2'
            )

            subject_cell = {
                'opening_message_id': opening_message_id,
                'menu_message_id': None,
                'subject_path': '',
                'posts_in_subject_channels': {
                    subjects_channels['']: sent_message.message_id
                }
            }

            CUR.execute(
                'UPDATE open_users SET subject = %s WHERE user_id = %s',
                (json.dumps(subject_cell), user_id)
            )
            CON.commit()

        else:
            speaking('user_already_open', message, reply=True, mono=True, eng=True)

    @staticmethod
    def mute(message, user_id):
        text = message.text

        split = re.split(' +', text)

        if len(split) == 1:
            CUR.execute(
                'SELECT muted_until FROM muted_users WHERE user_id = %s',
                (user_id,)
            )
            query_result = CUR.fetchone()

            if not query_result:
                CUR.execute(
                    'INSERT INTO muted_users (user_id) VALUES (%s)',
                    (user_id,)
                )
                CON.commit()

                add_to_history(
                    timestamp=message.date,
                    type='bot_action',
                    user_id=user_id,
                    volunteer_id=message.from_user.id,
                    column_0='mute_user',
                    column_1=None,
                    column_2=None
                )

                speaking('user_have_been_muted_forever', message, reply=True, mono=True, eng=True)

                update_channel_posts(user_id)

            else:
                muted_until = query_result[0]

                if muted_until:
                    speaking('user_already_muted_until', message, reply=True, mono=True, add_info=str(muted_until),
                             eng=True)
                else:
                    speaking('user_already_muted_forever', message, reply=True, mono=True, eng=True)

        elif len(split) == 2 and split[1].isdigit():
            mute_value = int(split[1])

            if 1 <= mute_value <= 365:
                CUR.execute(
                    'SELECT muted_until FROM muted_users WHERE user_id = %s',
                    (user_id,)
                )
                query_result = CUR.fetchone()

                if not query_result:
                    until_datetime = message.date.replace(tzinfo=None) + datetime.timedelta(days=mute_value)

                    CUR.execute(
                        'INSERT INTO muted_users (user_id, muted_until) VALUES (%s, %s)',
                        (user_id, until_datetime)
                    )
                    CON.commit()

                    speaking('user_have_been_muted_until', message, reply=True, mono=True,
                             add_info=str(until_datetime), eng=True)

                    update_channel_posts(user_id)

                    add_to_history(
                        timestamp=message.date,
                        type='bot_action',
                        user_id=user_id,
                        volunteer_id=message.from_user.id,
                        column_0='mute_user',
                        column_1=mute_value,
                        column_2=None
                    )

                else:
                    muted_until = query_result[0]

                    if muted_until:
                        speaking('user_already_muted_until', message, reply=True, mono=True,
                                 add_info=str(muted_until), eng=True)
                    else:
                        speaking('user_already_muted_forever', message, reply=True, mono=True, eng=True)

            else:
                speaking('mute_value_must_be_in_range', message, reply=True, mono=True, eng=True)

        else:
            speaking('bad_entered_command', message, reply=True, mono=True, eng=True)

    @staticmethod
    def unmute(message, user_id):
        CUR.execute(
            'SELECT 1 FROM muted_users WHERE user_id = %s',
            (user_id,)
        )
        query_result = CUR.fetchone()

        if query_result:
            CUR.execute(
                'DELETE FROM muted_users WHERE user_id = %s',
                (user_id,)
            )
            CON.commit()

            add_to_history(
                timestamp=message.date,
                type='bot_action',
                user_id=user_id,
                volunteer_id=message.from_user.id,
                column_0='unmute_user',
                column_1=None,
                column_2=None
            )

            speaking('user_have_been_unmuted', message, reply=True, mono=True, eng=True)

            update_channel_posts(user_id)

        else:
            speaking('user_not_muted', message, reply=True, mono=True, eng=True)

    @staticmethod
    def delete_message(message):
        reply_to_message = message.reply_to_message

        if reply_to_message.from_user.id != 777000:
            CUR.execute(
                'SELECT chat_id_1, message_id_1 FROM for_updating_messages WHERE chat_id_0 = %s AND message_id_0 = %s',
                (reply_to_message.chat.id, reply_to_message.message_id)
            )
            query_result = CUR.fetchone()

            if query_result:
                chat_id = query_result[0]
                message_id = query_result[1]

                try:
                    tg_delay(chat_id)
                    BOT.delete_message(chat_id, message_id)

                    speaking('message_deleted', message, reply=True, mono=True, eng=True)

                    # add to history

                    # history_column_1 = None
                    # history_column_2 = None
                    #
                    # if reply_to_message.text:
                    #     history_column_1 = 'text'
                    #     history_column_2 = reply_to_message.text
                    #
                    # elif reply_to_message.photo:
                    #     history_column_1 = 'photo'
                    #     history_column_2 = f'{reply_to_message.photo[-1].file_id}\n{reply_to_message.caption}'
                    #
                    # elif reply_to_message.sticker:
                    #     history_column_1 = 'sticker'
                    #     history_column_2 = reply_to_message.sticker.file_id
                    #
                    # elif reply_to_message.video:
                    #     history_column_1 = 'video'
                    #     history_column_2 = f'{reply_to_message.video.file_id}\n{reply_to_message.caption}'
                    #
                    # elif reply_to_message.audio:
                    #     history_column_1 = 'audio'
                    #     history_column_2 = f'{reply_to_message.audio.file_id}\n{reply_to_message.caption}'
                    #
                    # elif reply_to_message.voice:
                    #     history_column_1 = 'voice'
                    #     history_column_2 = f'{reply_to_message.voice.file_id}\n{reply_to_message.caption}'
                    #
                    # elif reply_to_message.video_note:
                    #     history_column_1 = 'video_note'
                    #     history_column_2 = reply_to_message.video_note.file_id
                    #
                    # elif reply_to_message.animation:
                    #     history_column_1 = 'animation'
                    #     history_column_2 = f'{reply_to_message.animation.file_id}\n{reply_to_message.caption}'
                    #
                    # elif reply_to_message.document:
                    #     history_column_1 = 'document'
                    #     history_column_2 = f'{reply_to_message.document.file_id}\n{reply_to_message.caption}'
                    # else:
                    #     history_column_1 = 'other_message_type'
                    #     history_column_2 = None

                    history_column_1, history_column_2 = get_column_1_and_column_2(reply_to_message)

                    add_to_history(
                        timestamp=message.date,
                        type='deleted_message',
                        user_id=chat_id,
                        volunteer_id=message.from_user.id,
                        column_0=reply_to_message.message_id,
                        column_1=history_column_1,
                        column_2=history_column_2
                    )

                except telegram.error.BadRequest as exc:
                    reason = '\n\n' + str(exc)
                    speaking('message_not_deleted_because', message, reply=True, mono=True, add_info=reason, eng=True)

            else:
                speaking('message_not_deleted_because_not_found_in_bot_db', message, reply=True, mono=True, eng=True)

        else:
            speaking('use_reply_with_del_command', message, reply=True, mono=True, eng=True)

    @staticmethod
    def subject_or_close(mode, message, user_id):
        assert mode in {'subject', 'close'}

        CUR.execute(
            'SELECT subject FROM open_users WHERE user_id = %s',
            (user_id,)
        )
        query_result = CUR.fetchone()

        if query_result:
            subject_cell = query_result[0]

            if subject_cell:
                opening_message_id = subject_cell['opening_message_id']
                subject_path = subject_cell['subject_path']
                if subject_path:
                    subject_list = subject_path.split('/')
                else:
                    subject_list = []
                posts_in_subject_channels = subject_cell['posts_in_subject_channels']
            else:
                opening_message_id = None
                subject_path = ''
                subject_list = []
                posts_in_subject_channels = {}

            subject_dir_list = get_subject_dir_list(subject_path)

            if subject_dir_list is False:
                report = f'info\n' \
                         f'\n' \
                         f'invalid subject_path\n' \
                         f'\n' \
                         f'subject_path: "{subject_path}"\n' \
                         f'\n' \
                         f'{datetime.datetime.utcnow()}\n'

                print(report + separator)

                tg_delay(log_chat_id)
                BOT.send_message(log_chat_id, report)

                return

            text = ''
            for i in subject_list:
                text += f'> {i}\n'
            if not text:
                text = 'empty'

            reply_markup = get_subject_reply_markup(mode, subject_path, subject_dir_list, user_id)

            tg_delay(group_chat_id)
            sent_message = BOT.send_message(
                group_chat_id,
                text,
                reply_to_message_id=message.message_id,
                reply_markup=reply_markup
            )

            new_subject_cell = {
                'opening_message_id': opening_message_id,
                'menu_message_id': sent_message.message_id,
                'subject_path': subject_path,
                'posts_in_subject_channels': posts_in_subject_channels
            }

            CUR.execute(
                'UPDATE open_users SET subject = %s WHERE user_id = %s',
                (json.dumps(new_subject_cell), user_id)
            )
            CON.commit()

        else:
            speaking('this_user_is_not_open', message, reply=True, mono=True, eng=True)


def subject_callback(update):
    callback_query = update.callback_query
    data = callback_query.data

    if callback_query.message.chat.id != group_chat_id:
        return

    splited = data.split(':', maxsplit=2)

    if len(splited) != 3:
        return

    mode = splited[0]
    user_id = int(splited[1])
    third_part = splited[2]

    if mode not in {'subject', 'close'}:
        return

    if callback_query.from_user.id != callback_query.message.reply_to_message.from_user.id:
        BOT.answer_callback_query(
            callback_query.id,
            'This message is not for you. Use appropriate /command.',
            show_alert=True
        )
        return

    CUR.execute(
        'SELECT subject FROM open_users WHERE user_id = %s',
        (user_id,)
    )
    query_result = CUR.fetchone()

    if query_result:
        subject_cell = query_result[0]

        if not subject_cell:
            BOT.answer_callback_query(
                callback_query.id,
                'This message is inactive. Use appropriate /command.',
                show_alert=True
            )
            return

        opening_message_id = subject_cell['opening_message_id']

        menu_message_id = subject_cell['menu_message_id']
        if callback_query.message.message_id != menu_message_id:
            BOT.answer_callback_query(
                callback_query.id,
                'This message is inactive. Find the newest message bellow or use appropriate /command.',
                show_alert=True
            )
            return

        subject_path = subject_cell['subject_path']
        if subject_path:
            old_subject_list = subject_path.split('/')
        else:
            old_subject_list = []

        if third_part == 'ok':
            if mode == 'subject':
                text = ''
                for i in old_subject_list:
                    text += f'> {i}\n'
                if not text:
                    text = 'empty\n'
                text += '\n✅'

                try:
                    tg_delay(callback_query.message.chat.id)
                    BOT.edit_message_text(
                        text,
                        callback_query.message.chat.id,
                        callback_query.message.message_id
                    )
                except telegram.error.BadRequest as exc:
                    error_text = 'Message is not modified: specified new message content and reply markup are ' \
                                 'exactly the same as a current content and reply markup of the message'

                    if str(exc) == error_text:
                        pass
                    else:
                        raise exc

            elif mode == 'close':
                close_user(callback_query, user_id)
            return
        elif third_part == '❌':
            tg_delay(callback_query.message.chat.id)
            try:
                BOT.delete_message(
                    callback_query.message.chat.id,
                    callback_query.message.message_id
                )
            except telegram.error.BadRequest as exc:
                error_text = "Message can't be deleted"

                if str(exc) == error_text:
                    edited_text = '❌'

                    BOT.edit_message_text(
                        edited_text,
                        callback_query.message.chat.id,
                        callback_query.message.message_id
                    )
                else:
                    raise exc
            return
        elif third_part == '⬅':
            new_subject_list = old_subject_list[0:-1]
        else:
            new_subject_list = old_subject_list.copy()
            new_subject_list.append(third_part)

        new_subject_path = '/'.join(new_subject_list)

        subject_dir_list = get_subject_dir_list(new_subject_path)

        if subject_dir_list is False:
            report = f'info\n' \
                     f'\n' \
                     f'invalid new_subject_path\n' \
                     f'\n' \
                     f'new_subject_path: "{new_subject_path}"\n' \
                     f'\n' \
                     f'callback_query.id: {callback_query.id}\n' \
                     f'\n' \
                     f'{datetime.datetime.utcnow()}\n'

            print(report + separator)

            tg_delay(log_chat_id)
            BOT.send_message(log_chat_id, report)

            return

        text = ''
        for i in new_subject_list:
            text += f'> {i}\n'
        if not text:
            text = 'empty'

        reply_markup = get_subject_reply_markup(mode, new_subject_path, subject_dir_list, user_id)

        tg_delay(callback_query.message.chat.id)
        BOT.edit_message_text(
            text,
            callback_query.message.chat.id,
            callback_query.message.message_id,
            reply_markup=reply_markup
        )

        new_subject_channels_set = set()
        for key in subjects_channels:
            if new_subject_path.startswith(key):
                new_subject_channels_set.add(subjects_channels[key])

        old_posts_in_subject_channels = {}
        for key in subject_cell['posts_in_subject_channels']:
            old_posts_in_subject_channels[int(key)] = subject_cell['posts_in_subject_channels'][key]

        old_subject_channels_set = set(old_posts_in_subject_channels.keys())

        new_subject_cell = {
            'opening_message_id': opening_message_id,
            'menu_message_id': menu_message_id,
            'subject_path': new_subject_path,
            'posts_in_subject_channels': subject_cell['posts_in_subject_channels']
        }

        CUR.execute(
            'UPDATE open_users SET subject = %s WHERE user_id = %s',
            (json.dumps(new_subject_cell), user_id)
        )
        CON.commit()

        text = channel_post_text(user_id, mode=1)

        new_channel_posts_dict = {}
        ignore_update_chats_set = set()
        for chat_id in new_subject_channels_set - old_subject_channels_set:
            ignore_update_chats_set.add(chat_id)

            tg_delay(chat_id)
            sent_message = BOT.send_message(
                chat_id,
                text,
                parse_mode='MarkdownV2'
            )

            new_channel_posts_dict[chat_id] = sent_message.message_id

        for chat_id in old_subject_channels_set - new_subject_channels_set:
            tg_delay(chat_id)
            try:
                BOT.delete_message(
                    chat_id,
                    old_posts_in_subject_channels[chat_id],
                )
            except telegram.error.BadRequest as exc:
                error_text = "Message can't be deleted"

                if str(exc) == error_text:
                    edited_text = '❌ the post is not actual\n' \
                                  '\n' \
                                  'the post is too old and cannot be deleted by bot'

                    BOT.edit_message_text(
                        edited_text,
                        chat_id,
                        old_posts_in_subject_channels[chat_id]
                    )

                else:
                    raise exc

        actual_posts_in_subject_channels = {}
        for current_dict in old_posts_in_subject_channels, new_channel_posts_dict:
            for chat_id in current_dict:
                if chat_id in new_subject_channels_set:
                    actual_posts_in_subject_channels[chat_id] = current_dict[chat_id]

        new_subject_cell = {
            'opening_message_id': opening_message_id,
            'menu_message_id': menu_message_id,
            'subject_path': new_subject_path,
            'posts_in_subject_channels': actual_posts_in_subject_channels
        }

        CUR.execute(
            'UPDATE open_users SET subject = %s WHERE user_id = %s',
            (json.dumps(new_subject_cell), user_id)
        )
        CON.commit()

        update_channel_posts(user_id, ignore_update_chats_set)

        BOT.answer_callback_query(callback_query.id)

    else:
        BOT.answer_callback_query(
            callback_query.id,
            'This user is not open.',
            show_alert=True
        )


def get_subject_dir_list(subject_path: str):
    if subject_path:
        subject_path = subject_path.strip()
        subject_list = subject_path.split('/')

        gag = subjects_dict
        for item in subject_list:
            if isinstance(gag, dict):
                if item in gag:
                    gag = gag[item]
                else:
                    return False
            elif gag is None:
                return False

        if isinstance(gag, dict):
            return list(gag.keys())
        elif gag is None:
            return []

    else:
        return list(subjects_dict.keys())


def get_subject_reply_markup(mode, subject_path, subject_dir_list, user_id):
    if mode == 'subject':
        ok_emoji = '☑️'
    elif mode == 'close':
        ok_emoji = '✅'
    else:
        assert False

    first_buttons_line = [
        telegram.InlineKeyboardButton(ok_emoji, callback_data=f'{mode}:{user_id}:ok')
    ]

    if mode == 'close':
        first_buttons_line.insert(
            0,
            telegram.InlineKeyboardButton('❌', callback_data=f'{mode}:{user_id}:❌')
        )

    if subject_path:
        first_buttons_line.insert(
            0,
            telegram.InlineKeyboardButton('⬅️', callback_data=f'{mode}:{user_id}:⬅')
        )

    keyboard = [first_buttons_line] + [
        [telegram.InlineKeyboardButton(i, callback_data=f'{mode}:{user_id}:{i}')]
        for i in subject_dir_list
    ]

    reply_markup = telegram.InlineKeyboardMarkup(keyboard)

    return reply_markup


def close_user(callback_query, user_id):
    CUR.execute(
        'SELECT subject FROM open_users WHERE user_id = %s',
        (user_id,)
    )
    query_result = CUR.fetchone()

    if query_result:
        subject_cell = query_result[0]

        if subject_cell:
            opening_message_id = subject_cell['opening_message_id']
            subject_path = subject_cell['subject_path']
        else:
            opening_message_id = None
            subject_path = None

        CUR.execute(
            'DELETE FROM open_users WHERE user_id = %s',
            (user_id,)
        )
        CON.commit()

        if not subject_path:
            subject_path = None

        add_to_history(
            timestamp=datetime.datetime.utcnow(),
            type='bot_action',
            user_id=user_id,
            volunteer_id=callback_query.from_user.id,
            column_0='close_user',
            column_1=subject_path,
            column_2=opening_message_id
        )

        if not subject_path:
            subject_path = 'empty'

        volunteer_info = get_tg_user_info(callback_query.from_user)
        text = f'✅ `user was closed`\n' \
               f'by {escape_markdown(volunteer_info)}\n' \
               f'subject: {escape_markdown(subject_path)}'

        tg_delay(callback_query.message.chat.id)
        BOT.edit_message_text(
            text,
            callback_query.message.chat.id,
            callback_query.message.message_id,
            parse_mode='MarkdownV2'
        )

        for chat_id in subject_cell['posts_in_subject_channels']:
            tg_delay(int(chat_id))

            try:
                BOT.delete_message(
                    int(chat_id),
                    subject_cell['posts_in_subject_channels'][chat_id],
                )
            except telegram.error.BadRequest as exc:
                error_text = "Message can't be deleted"

                if str(exc) == error_text:
                    edited_text = '🟢 closed\n' \
                                  '\n' \
                                  'the post of closed user is too old and cannot be deleted by bot'

                    BOT.edit_message_text(
                        edited_text,
                        int(chat_id),
                        subject_cell['posts_in_subject_channels'][chat_id]
                    )

                else:
                    raise exc

        update_channel_posts(user_id)

    else:
        BOT.answer_callback_query(
            callback_query.id,
            'This user is not open.',
            show_alert=True
        )


def channel_post_text(tg_user_or_user_id, mode=0):
    if isinstance(tg_user_or_user_id, telegram.user.User):
        tg_user = tg_user_or_user_id
    else:
        user_id = tg_user_or_user_id
        tg_user = BOT.get_chat_member(user_id, user_id).user  # if bot is blocked by user - all fine

    CUR.execute(
        'SELECT muted_until FROM muted_users WHERE user_id = %s',
        (tg_user.id,)
    )
    query_result = CUR.fetchone()

    if query_result:
        muted = True
        muted_until = query_result[0]
    else:
        muted = False
        muted_until = None

    CUR.execute(
        'SELECT opening_time, volunteer_id, subject FROM open_users WHERE user_id = %s',
        (tg_user.id,)
    )
    query_result = CUR.fetchone()

    if query_result:
        open = True
        opening_time, volunteer_id, subject_cell = query_result

        if volunteer_id:
            status_line = f'🟡 open {opening_time}, taken by {get_tg_user_info(volunteer_id)}'
        else:
            status_line = f'🔴 open {opening_time}, not taken'

        if subject_cell:
            subject_path = subject_cell['subject_path']
            if subject_path:
                subject = subject_path
            else:
                subject = 'empty'
        else:
            subject = 'empty'
    else:
        open = False
        subject = ''
        status_line = '🟢 closed'

    language = get_user_language(tg_user)

    text = ''
    if muted:
        muted_text = '🚫 user muted'
        if muted_until:
            muted_text += f', until {escape_markdown(str(muted_until))}'
        else:
            muted_text += ', forever'
        text += muted_text + '\n\n'
    text += escape_markdown(status_line) + '\n\n'
    if open:
        text += f'subject: {escape_markdown(subject)}' + '\n\n'
    text += escape_markdown(get_tg_user_info(tg_user)) + '\n\n'
    text += f'lang: {language}' + '\n\n'

    if mode:
        CUR.execute(
            'SELECT channel_message_id FROM message_ids WHERE user_id = %s',
            (tg_user.id,)
        )
        query_result = CUR.fetchone()

        if query_result:
            channel_message_id = query_result[0]
            text += f'[link to post]({channel_link}/{channel_message_id})'
    else:
        text += escape_markdown(f'#user_{tg_user.id}')

    return text


def create_channel_post(message, not_first=False):
    CUR.execute(
        'SELECT 1 FROM languages_of_users WHERE user_id = %s',
        (message.from_user.id,)
    )
    query_result = CUR.fetchone()

    if not query_result:
        CUR.execute(
            'INSERT INTO languages_of_users (user_id, language) VALUES (%s, %s)',
            (
                message.from_user.id,
                tg_languages_dict.get(message.from_user.language_code, 'eng')
            )
        )
        CON.commit()

        add_to_history(
            timestamp=message.date,
            type='bot_action',
            user_id=message.from_user.id,
            volunteer_id=None,
            column_0='new_user',
            column_1=None,
            column_2=None
        )

    CUR.execute(
        'DELETE FROM message_ids WHERE user_id = %s',
        (message.from_user.id,)
    )
    CON.commit()

    tg_delay(channel_chat_id)
    sent_message = BOT.send_message(
        channel_chat_id,
        channel_post_text(message.from_user),
        parse_mode='MarkdownV2'
    )

    MAP_OF_CHANNEL_MESSAGE_ID_AND_USER_ID[sent_message.message_id] = message.from_user.id
    QUEUE_OF_MESSAGES_DICT[message.from_user.id] = [message]
    QUEUE_OF_EDITED_MESSAGES_DICT[message.from_user.id] = []

    if not_first:
        class NotFirstChannelPostMarker:
            pass

        marker = NotFirstChannelPostMarker()
        QUEUE_OF_MESSAGES_DICT[message.from_user.id].insert(0, marker)


def update_channel_posts(tg_user_or_user_id, ignore_update_chats_set=None):
    if ignore_update_chats_set is None:
        ignore_update_chats_set = set()

    def try_edit_message(chat_id, message_id, text):
        try:
            tg_delay(chat_id)
            BOT.edit_message_text(
                text,
                chat_id,
                message_id,
                parse_mode='MarkdownV2'
            )

        except telegram.error.BadRequest as exc:
            error_0_text = 'Message is not modified: ' \
                           'specified new message content and reply markup are exactly the same ' \
                           'as a current content and reply markup of the message'
            error_1_text = 'Message_id_invalid'
            error_2_text = 'Message to edit not found'

            if str(exc) in {error_0_text, error_1_text, error_2_text}:
                report = f'update_channel_post\n' \
                         f'post_id: {channel_message_id}\n' \
                         f'\n' \
                         f'{str(exc)}\n' \
                         f'\n' \
                         f'{datetime.datetime.utcnow()}'

                print(report + separator)

                tg_delay(log_chat_id)
                BOT.send_message(log_chat_id, report)
            else:
                raise exc

    if isinstance(tg_user_or_user_id, telegram.user.User):
        tg_user = tg_user_or_user_id
        user_id = tg_user.id
    else:
        user_id = tg_user_or_user_id
        tg_user = BOT.get_chat_member(user_id, user_id).user  # if bot is blocked by user - all fine

    CUR.execute(
        'SELECT channel_message_id FROM message_ids WHERE user_id = %s',
        (user_id,)
    )
    query_result = CUR.fetchone()

    if query_result:
        channel_message_id = query_result[0]

        text = channel_post_text(tg_user)

        if channel_chat_id not in ignore_update_chats_set:
            try_edit_message(channel_chat_id, channel_message_id, text)

        CUR.execute(
            'SELECT subject FROM open_users WHERE user_id = %s',
            (user_id,)
        )
        query_result = CUR.fetchone()

        if query_result:
            subject_cell = query_result[0]

            if subject_cell:
                messages = {}
                for key in subject_cell['posts_in_subject_channels']:
                    messages[int(key)] = subject_cell['posts_in_subject_channels'][key]

                text = channel_post_text(tg_user, mode=1)

                for chat_id in messages:
                    if chat_id not in ignore_update_chats_set:
                        try_edit_message(chat_id, messages[chat_id], text)


def tg_delay(target_chat_id):
    if tg_delays:
        if target_chat_id > 0:
            if target_chat_id in LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT:

                delay_value = 1

                time_difference = time() - LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT[target_chat_id]
                if time_difference < delay_value:
                    sleep(delay_value - time_difference)

            LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT[target_chat_id] = time()

        elif target_chat_id < 0:
            if target_chat_id in LAST_TIME_OF_MESSAGE_FROM_BOT_TO_CHAT_DICT:

                delay_value = 3

                time_difference = time() - LAST_TIME_OF_MESSAGE_FROM_BOT_TO_CHAT_DICT[target_chat_id]
                if time_difference < delay_value:
                    sleep(delay_value - time_difference)

            LAST_TIME_OF_MESSAGE_FROM_BOT_TO_CHAT_DICT[target_chat_id] = time()


def my_forward_message(to_chat, message, reply_to_message_id=None):
    sent_message = None
    history_column_0 = None
    history_column_1 = None
    history_column_2 = None

    try:
        tg_delay(to_chat)

        if message.text \
                and message.via_bot and message.via_bot.id in tg_wallet_bots_dict:
            history_column_1 = tg_wallet_bots_dict[message.via_bot.id]
            history_column_2 = message.text

            sent_message = BOT.send_message(
                to_chat,
                f'{tg_wallet_bots_dict[message.via_bot.id]}\n{message.text}',
                reply_to_message_id=reply_to_message_id,
                reply_markup=message.reply_markup
            )

        else:
            if message.text:
                # if bool(re.match('test_error.*', message.text)):
                if message.text.startswith('test_error'):
                    test_error(message)

            sent_message = BOT.copy_message(
                to_chat,
                message.chat.id,
                message.message_id,
                reply_to_message_id=reply_to_message_id
            )

            # if message.text:
            #     history_column_1 = 'text'
            #     history_column_2 = message.text
            #
            # elif message.photo:
            #     history_column_1 = 'photo'
            #     history_column_2 = f'{message.photo[-1].file_id}\n{message.caption}'
            #
            # elif message.sticker:
            #     history_column_1 = 'sticker'
            #     history_column_2 = message.sticker.file_id
            #
            # elif message.video:
            #     history_column_1 = 'video'
            #     history_column_2 = f'{message.video.file_id}\n{message.caption}'
            #
            # elif message.audio:
            #     history_column_1 = 'audio'
            #     history_column_2 = f'{message.audio.file_id}\n{message.caption}'
            #
            # elif message.voice:
            #     history_column_1 = 'voice'
            #     history_column_2 = f'{message.voice.file_id}\n{message.caption}'
            #
            # elif message.video_note:
            #     history_column_1 = 'video_note'
            #     history_column_2 = message.video_note.file_id
            #
            # elif message.animation:
            #     history_column_1 = 'animation'
            #     history_column_2 = f'{message.animation.file_id}\n{message.caption}'
            #
            # elif message.document:
            #     history_column_1 = 'document'
            #     history_column_2 = f'{message.document.file_id}\n{message.caption}'
            #
            # else:
            #     history_column_1 = 'other_message_type'
            #     history_column_2 = None

            history_column_1, history_column_2 = get_column_1_and_column_2(message)

    except telegram.error.BadRequest as exc:
        if str(exc) == 'Replied message not found':
            create_channel_post(message, not_first=True)

            report = f'replied message not found, created new channel post\n' \
                     f'old group_message_id: {reply_to_message_id}\n' \
                     f'{datetime.datetime.utcnow()}'

            print(report + separator)

            tg_delay(log_chat_id)
            BOT.send_message(log_chat_id, report)

        else:
            raise exc

    except telegram.error.Unauthorized as exc:
        if str(exc) == 'Forbidden: bot was blocked by the user':
            speaking('bot_was_blocked_by_the_user', message, reply=True, mono=True, eng=True)
        else:
            raise exc

    if to_chat == group_chat_id:
        user_id = message.from_user.id
        volunteer_id = None
    elif to_chat > 0:
        user_id = to_chat
        volunteer_id = message.from_user.id
        history_column_0 = message.message_id
    else:
        assert False

    if sent_message:
        CUR.execute(
            '''
                insert into for_updating_messages (
                    "timestamp",
                    chat_id_0,
                    message_id_0,
                    chat_id_1,
                    message_id_1
                )
                values (%s, %s, %s, %s, %s)
            ''',
            (
                message.date,
                message.chat.id,
                message.message_id,
                to_chat,
                sent_message.message_id
            )
        )
        CON.commit()

        if to_chat == group_chat_id:
            history_column_0 = sent_message.message_id

    add_to_history(
        timestamp=message.date,
        type='message',
        user_id=user_id,
        volunteer_id=volunteer_id,
        column_0=history_column_0,
        column_1=history_column_1,
        column_2=history_column_2
    )


def get_column_1_and_column_2(message):
    if message.text:
        history_column_1 = 'text'
        history_column_2 = message.text

    elif message.photo:
        photo = message.photo[-1]
        history_column_1 = 'photo'
        history_column_2 = f'{photo.file_unique_id}\n' \
                           f'{photo.file_id}\n' \
                           f'{message.caption}'

    elif message.sticker:
        sticker = message.sticker
        history_column_1 = 'sticker'
        history_column_2 = f'{sticker.file_unique_id}\n' \
                           f'{sticker.file_id}'

    elif message.video:
        video = message.video
        history_column_1 = 'video'
        history_column_2 = f'{video.file_unique_id}\n' \
                           f'{video.file_id}\n' \
                           f'{message.caption}'

    elif message.audio:
        audio = message.audio
        history_column_1 = 'audio'
        history_column_2 = f'{audio.file_unique_id}\n' \
                           f'{audio.file_id}\n' \
                           f'{message.caption}'

    elif message.voice:
        voice = message.voice
        history_column_1 = 'voice'
        history_column_2 = f'{voice.file_unique_id}\n' \
                           f'{voice.file_id}\n' \
                           f'{message.caption}'

    elif message.video_note:
        video_note = message.video_note
        history_column_1 = 'video_note'
        history_column_2 = f'{video_note.file_unique_id}\n' \
                           f'{video_note.file_id}'

    elif message.animation:
        animation = message.animation
        history_column_1 = 'animation'
        history_column_2 = f'{animation.file_unique_id}\n' \
                           f'{animation.file_id}\n' \
                           f'{message.caption}'

    elif message.document:
        document = message.document
        history_column_1 = 'document'
        history_column_2 = f'{document.file_unique_id}\n' \
                           f'{document.file_id}\n' \
                           f'{message.caption}'

    else:
        history_column_1 = 'other_message_type'
        history_column_2 = None

    return history_column_1, history_column_2


def speaking(speaking_keyword, message, reply=False, mono=False, cut_big_text=False, add_info=None, eng=False,
             markdown=False, return_message_id=False):
    # !
    # don't use mono=True and cut_bit_text=True together
    # don't use markdown=True and cut_bit_text=True together

    if eng:
        user_language = 'eng'
    else:
        user_language = get_user_language(message)

    if speaking_keyword in speaking_dict:
        dict_of_phrase = speaking_dict[speaking_keyword]

        if user_language in dict_of_phrase:
            answer = dict_of_phrase[user_language]
        else:
            answer = dict_of_phrase.get('eng', None)
    else:
        answer = None

    if answer:
        if reply:
            reply_to_message_id = message.message_id
        else:
            reply_to_message_id = None

        if add_info:
            answer = answer + add_info

        if markdown:
            parse_mode = 'MarkdownV2'
        else:
            parse_mode = None

            if mono:
                answer = f'`{answer}`'
                parse_mode = 'MarkdownV2'
            else:
                parse_mode = None

        if cut_big_text:
            answer = truncate_big_text(0, answer)

        tg_delay(message.chat.id)
        sent_message = BOT.send_message(
            message.chat.id,
            answer,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=True,
            parse_mode=parse_mode,
            disable_web_page_preview=True
        )

        if return_message_id:
            return sent_message.message_id

    else:
        report = f'no answer in speaking()\n' \
                 f'\n' \
                 f'answer_keyword: "{speaking_keyword}"\n' \
                 f'user_language: {user_language}\n' \
                 f'user_id: {message.from_user.id}\n' \
                 f'\n' \
                 f'message time: {message.date}\n' \
                 f'bot time: {datetime.datetime.utcnow()}'

        tg_delay(log_chat_id)
        BOT.send_message(log_chat_id, report)


def get_tg_user_info(tg_user_or_user_id):
    if isinstance(tg_user_or_user_id, telegram.user.User):
        tg_user = tg_user_or_user_id
    else:
        user_id = tg_user_or_user_id
        tg_user = BOT.get_chat_member(user_id, user_id).user  # if bot is blocked by user - all fine

    text = ''

    if tg_user.first_name:
        text += tg_user.first_name

    if tg_user.last_name:
        text += ' ' + tg_user.last_name

    if tg_user.username:
        text += ' @' + tg_user.username

    return text


def get_user_language(tg_message_or_user):
    if isinstance(tg_message_or_user, telegram.Message):
        message = tg_message_or_user
        tg_user = message.from_user
    elif isinstance(tg_message_or_user, telegram.User):
        message = None
        tg_user = tg_message_or_user
    else:
        assert False

    CUR.execute(
        'SELECT language FROM languages_of_users WHERE user_id = %s',
        (tg_user.id,)
    )
    query_result = CUR.fetchone()

    if query_result:
        language = query_result[0]

    else:
        language = tg_languages_dict.get(tg_user.language_code, 'eng')

        if message:
            CUR.execute(
                'INSERT INTO languages_of_users (user_id, language) VALUES (%s, %s)',
                (message.from_user.id, language)
            )
            CON.commit()

            add_to_history(
                timestamp=message.date,
                type='bot_action',
                user_id=message.from_user.id,
                volunteer_id=None,
                column_0='new_user',
                column_1=None,
                column_2=None
            )

    return language


def is_volunteer(tg_user):
    try:
        status = BOT.get_chat_member(channel_chat_id, tg_user.id).status
    except telegram.error.BadRequest as exc:
        if str(exc) == 'User not found':
            status = 'never was member'
        else:
            raise exc

    if status in {'creator', 'administrator', 'member'}:
        return True
    else:
        return False


def truncate_big_text(mode, text: str):
    max_allowed_text_length = 4096

    if len(text) > max_allowed_text_length:
        delimiter = '......'

        if mode:
            text = delimiter + text[len(text) - (max_allowed_text_length - len(delimiter)):len(text)]
        else:
            text = text[0:max_allowed_text_length - len(delimiter)] + delimiter

    return text


def escape_markdown(string: str):
    characters_tuple = ('\\', '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!')

    for char in characters_tuple:
        string = string.replace(char, '\\' + char)

    return string


def add_to_history(**kwargs):
    CUR.execute(
        '''
            insert into history (
                "timestamp",
                "type",
                user_id,
                volunteer_id,
                column_0,
                column_1,
                column_2
            )
            values (%s, %s, %s, %s, %s, %s, %s)
        ''',
        (
            kwargs['timestamp'],
            kwargs['type'],
            kwargs['user_id'],
            kwargs['volunteer_id'],
            kwargs['column_0'],
            kwargs['column_1'],
            kwargs['column_2']
        )
    )
    CON.commit()


def cleaning():
    random_value = 0.01

    if random.random() < random_value:
        choice = random.choice(range(6))

        if choice == 0:
            Cleaning.clean_LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT()
        elif choice == 1:
            Cleaning.clean_LAST_TIME_OF_GREETING_MESSAGE_DICT()
        elif choice == 2:
            Cleaning.clean_LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT()
        elif choice == 3:
            Cleaning.clean_for_updating_messages_table()
        elif choice == 4:
            Cleaning.clean_updates_table()
        elif choice == 5:
            Cleaning.clean_flood_control_table()


class Cleaning:
    @staticmethod
    def clean_LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT():
        live_time_value = 86400

        current_time = time()

        for dict_key in LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT.copy():
            if current_time - LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT[dict_key] > live_time_value:
                del LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT[dict_key]

        add_to_history(
            timestamp=datetime.datetime.utcnow(),
            type='bot_action',
            user_id=None,
            volunteer_id=None,
            column_0='cleaning',
            column_1='LAST_TIME_OF_MESSAGE_FROM_BOT_TO_USER_DICT',
            column_2=None
        )

    @staticmethod
    def clean_LAST_TIME_OF_GREETING_MESSAGE_DICT():
        live_time_value = 86400

        current_time = time()

        for dict_key in LAST_TIME_OF_GREETING_MESSAGE_DICT.copy():
            if current_time - LAST_TIME_OF_GREETING_MESSAGE_DICT[dict_key] > live_time_value:
                del LAST_TIME_OF_GREETING_MESSAGE_DICT[dict_key]

        add_to_history(
            timestamp=datetime.datetime.utcnow(),
            type='bot_action',
            user_id=None,
            volunteer_id=None,
            column_0='cleaning',
            column_1='LAST_TIME_OF_GREETING_MESSAGE_DICT',
            column_2=None
        )

    @staticmethod
    def clean_LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT():
        live_time_value = 86400

        current_time = time()

        for dict_key in LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT.copy():
            if current_time - LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT[dict_key] > live_time_value:
                del LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT[dict_key]

        add_to_history(
            timestamp=datetime.datetime.utcnow(),
            type='bot_action',
            user_id=None,
            volunteer_id=None,
            column_0='cleaning',
            column_1='LAST_TIME_OF_FLOOD_CONTROL_CAUTION_DICT',
            column_2=None
        )

    @staticmethod
    def clean_for_updating_messages_table():
        dt = datetime.datetime.utcnow() - datetime.timedelta(days=30)

        CUR.execute(
            'DELETE FROM for_updating_messages WHERE "timestamp" < %s',
            (dt,)
        )
        CON.commit()

        add_to_history(
            timestamp=datetime.datetime.utcnow(),
            type='bot_action',
            user_id=None,
            volunteer_id=None,
            column_0='cleaning',
            column_1='for_updating_messages_table',
            column_2=None
        )

    @staticmethod
    def clean_updates_table():
        dt = datetime.datetime.utcnow() - datetime.timedelta(days=30)

        CUR.execute(
            'DELETE FROM updates WHERE "timestamp" < %s',
            (dt,)
        )
        CON.commit()

        add_to_history(
            timestamp=datetime.datetime.utcnow(),
            type='bot_action',
            user_id=None,
            volunteer_id=None,
            column_0='cleaning',
            column_1='updates_table',
            column_2=None
        )

    @staticmethod
    def clean_flood_control_table():
        dt = datetime.datetime.utcnow() - datetime.timedelta(days=2)

        CUR.execute(
            'DELETE FROM flood_control WHERE "timestamp" < %s',
            (dt,)
        )
        CON.commit()

        add_to_history(
            timestamp=datetime.datetime.utcnow(),
            type='bot_action',
            user_id=None,
            volunteer_id=None,
            column_0='cleaning',
            column_1='flood_control_table',
            column_2=None
        )


def test_error(message):
    def error_0():
        raise Exception('gaga test_error')

    def error_1():
        CUR.execute('INSERT INTO languages_of_users VALUES (1168253329, \'eng\')')
        CON.commit()

    def error_2():
        BOT.send_message(DG_user_id, 'a' * 4097)

    ################

    if not message.text:
        return

    # if not bool(re.match('test_error.*', message.text)):
    if not message.text.startswith('test_error'):
        return

    if not is_volunteer(message.from_user):
        return

    text = message.text

    split = re.split(' +', text)

    if len(split) == 2 and split[1].isdigit():
        number = int(split[1])

        if number == 0:
            error_0()

        elif number == 1:
            error_1()

        elif number == 2:
            error_2()

    else:
        error_0()


def minor_error(exc):
    message = f'minor error\n' \
              f'{exc.__class__.__name__}: {str(exc)}\n' \
              f'{datetime.datetime.utcnow()}'

    print(message + separator)

    tg_delay(log_chat_id)
    BOT.send_message(log_chat_id, message, disable_notification=True)

    sleep(10)


def my_traceback(level, additional_information=None, update=None):
    global SHIT_COUNTER

    info_message = f'level {level}'

    if SHIT_COUNTER:
        info_message += f'\n\nSHIT_COUNTER: {SHIT_COUNTER}'

    info_message += f'\n\n{datetime.datetime.utcnow()}'

    if additional_information:
        info_message += f'\n\n{additional_information}'

    traceback_message = traceback.format_exc()

    print(info_message + '\n\n' + traceback_message + separator)

    try:
        tg_delay(log_chat_id)
        BOT.send_message(log_chat_id, truncate_big_text(0, info_message))

        tg_delay(log_chat_id)
        BOT.send_message(log_chat_id, truncate_big_text(1, traceback_message))

        if update and update.message:
            problem_message = 'problem message\n\n'

            problem_message += f'chat_id: {update.message.chat.id}\n'
            problem_message += f'message_id: {update.message.message_id}\n'
            if update.message.from_user:
                problem_message += f'user_id: {update.message.from_user.id}\n'

            speaking('mistake', update.message, reply=True, mono=True)

            tg_delay(log_chat_id)
            BOT.send_message(log_chat_id, truncate_big_text(0, problem_message))

            tg_delay(log_chat_id)
            BOT.forward_message(log_chat_id, update.message.chat.id, update.message.message_id)

    except:
        exception_in_my_traceback_message = '! exception in handling my_traceback))\n\n'
        exception_in_my_traceback_message += traceback.format_exc()

        print(exception_in_my_traceback_message + separator)

    sleep(2 ** SHIT_COUNTER)
    SHIT_COUNTER += 1

if __name__ == '__main__':
    print('RUNNING BOT')
    gaga()
