# Как помочь этому форку

Форк собирает короткие двухголосые аудиоуроки из открытых веб-страниц и озвучивает их локально. Работать с ним удобно: весь код, включая тесты, живёт в Docker-контейнере, а не в вашей системе.

## Стенд

```bash
docker compose up -d aidemy
```

Этого достаточно, чтобы запускать скрипты скилла и тесты. Модели голоса кладутся в `D:/llm/aidemy` (переменная пути в `docker-compose.yml`), образ несёт Python 3, beautifulsoup4 и ffmpeg.

## Тесты: только примонтированным деревом

```bash
docker compose --profile cpu run -T --rm --no-deps \
  -v "<путь к репозиторию>:/app" aidemy-cpu \
  python -m unittest discover -s tests
```

Причина именно такая форма: `docker compose exec` запускает код, запечённый в образ, а не тот, что лежит у вас в рабочем дереве, — вы получите зелёный прогон старых правок. `run` со монтированием `/app` меряет текущие файлы. `--no-deps` нужен, чтобы прогон не поднимал базу и остальную инфраструктуру; `--profile cpu` выбирает образ без CUDA.

## Коммиты этого форка

- `README.md` (русский) и `README_en.md` (английский) едут **в том же коммите, что и код**: документация, отстающая от дерева, считается битой.
- Сообщение коммита — русское с английским зеркалом ниже; в теле — что и почему, с цифрами из `git diff --numstat`, снятыми после последней правки файла.
- Перед `git commit` последний вызов — мерка утечек текста:

```bash
python -X utf8 <путь>/leakcheck/leakcheck.py --prose <каждый тронутый файл>
```

`rc=0` и «Чисто.» — иначе правка не коммитится.
- **Пуш делает сопровождающий форка, не автор ветки.** Ветка в `origin` — это уже опубликованное состояние: локальные коммиты, `git push` и merge в `main` остаются за ведющим.

## Что ещё стоит знать

- Гейт уроков (`skills/aidemy/scripts/check_lessons.py`) отклоняет ссылку на страницу, которой нет в `raw/`, и держит коридор слов по движку — обходите его правкой текста урока, а не ослаблением проверок.
- Окончания строк в дереве — CRLF (`core.autocrlf=true`); после ручной правки проверяйте, что голых LF не стало больше.
- Веб-страница (`web/app.py`) работает в домашней сети и защищена токеном; подробности — в `SECURITY.md`.

---

# How to help this fork

The fork turns open web pages into short two-voice audio lessons and synthesizes the voice locally. Everything, tests included, runs in a Docker container rather than on your machine.

## The stand

```bash
docker compose up -d aidemy
```

That is enough to run the skill scripts and the tests. Voice models live in `D:/llm/aidemy` (the path variable is in `docker-compose.yml`); the image carries Python 3, beautifulsoup4 and ffmpeg.

## Tests: mounted working tree only

```bash
docker compose --profile cpu run -T --rm --no-deps \
  -v "<path to the repository>:/app" aidemy-cpu \
  python -m unittest discover -s tests
```

The reason for this exact form: `docker compose exec` runs the code baked into the image, not the files in your working tree, so it reports green for edits that are not there anymore. `run` with `/app` mounted measures the current files. `--no-deps` keeps the database and the rest of the infrastructure out of the run; `--profile cpu` selects the image without CUDA.

## Commits in this fork

- `README.md` (Russian) and `README_en.md` (English) travel in **the same commit as the code**: documentation lagging behind the tree counts as broken.
- Commit message in Russian with an English mirror below it; the body says what and why, with the numbers taken from `git diff --numstat` after the last edit of the file.
- The last call before `git commit` is the text-leak measure:

```bash
python -X utf8 <path>/leakcheck/leakcheck.py --prose <each touched file>
```

It must return `rc=0` and «Чисто.» — otherwise the change does not get committed.
- **The maintainer pushes, not the branch author.** A branch in `origin` is already published state: local commits, `git push` and merges into `main` stay with the maintainer.

## Worth knowing

- The lesson gate (`skills/aidemy/scripts/check_lessons.py`) rejects a citation to a page missing from `raw/` and holds the word corridor per engine — fix the lesson text instead of loosening the checks.
- Line endings in the tree are CRLF (`core.autocrlf=true`); after a manual edit, verify that the count of bare LF did not grow.
- The web page (`web/app.py`) serves the home network and is guarded by a token; see `SECURITY.md`.
