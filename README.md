# TON VS Bot

## Instruction
* Guide for volunteers: https://telegra.ph/TON-help-bot-instrukciya-01-02


## Setup bot
* Place telegram token in `private/telegram_token` and postgres password in `private/postgres_password`.
* Build image: `docker-compose build`
* Run: `docker-compose up -d`

## Setup backups
* Place postgres password to `private/postgres_password`.
* Add line ```0 0 * * * `pwd`/backup.sh``` to crontab:
```crontab -l | { cat; echo "0 0 * * * `pwd`/backup.sh `pwd`/private/postgres_password"; } | sudo crontab -```
