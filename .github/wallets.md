# Как поддержать форк

Форк бесплатный, работает офлайн и не требует ключей API. Если коротко: помощь проекту — это прежде всего отзывы, воспроизводимые баг-репорты и правки. Если хочется поддержать автора деньгами, вот способы, которые реально работают из вашей страны.

## DonationAlerts

<https://www.donationalerts.com/r/bahooo>

Там карта, СБП и кошельки — выбор сервиса оставляет себе DonationAlerts, я его не контролирую.

## Крипто-кошельки

| Сеть / Network | Адрес / Address |
|---|---|
| Ethereum (ERC-20 совместимый адрес) | `0x984fE5Bfe7B1573063E20fb3722ba9d4A7a67F04` |
| TON (bounceable, workchain 0) | `UQCHOWrPc1SF_1ZK8pvZP-L1j4mGXmN8JPYrM9GUxJRdOMcf` |
| Bitcoin (native SegWit, P2WPKH) | `bc1q4ln0y35utxhdtkf2qnrnu6e784yyct4n25eu5y` |

Биткоин-адрес начинается с `bc1q` — это native SegWit, его принимают актуальные биржи и кошельки. При переводе выбирайте сеть Bitcoin и формат адреса bech32 (`bc1…`), а не `1…` или `3…`: от формата зависит комиссия, а на старых клиентах такой адрес просто не пройдёт.

Перед отправкой сверьте первые и последние шесть символов с этим файлом в `main` (`git log -1 --format=%H -- .github/wallets.md` скажет, когда он менялся в последний раз). Ethereum-адрес прошёл проверку контрольной суммы EIP-55: keccak-256 от строчки в нижнем регистре даёт ровно такое распределение регистра; мерка снята в контейнере стенда на `Crypto.Hash.keccak` (pycryptodome), оба канонических вектора keccak-256 совпали.

Bitcoin-адрес прошёл проверку контрольной суммы bech32 по BIP-173: BCH-полином от расширенной human-readable части и данных равен ровно 1; это witness-версия 0 с 20-байтовой программой, ей соответствует scriptPubKey `0014afe6f2469c59aed5d92a04c73e6b3e3d484c2eb3`. Сама проверка сверена на всех пятнадцати segwit-векторах самого BIP-173 (шесть валидных воспроизводят заявленный scriptPubKey, девять невалидных отклоняются) и независимо на эталонной python-реализации из приложения к тому же BIP: обратное кодирование выдаёт ровно эту строку. TON-адрес прошёл crc16-xmodem по 34 байтам тела (тег `c71f`), bounceable-флаг и workchain 0 совпали с подписью в таблице.

Никаких обязательств за донат: доступ к курсам, к коду и к релизам от него не зависит, приватных сборок нет.

---

# Supporting this fork

The fork is free, runs offline and needs no API keys. Short version: the most useful help is a reproducible bug report, a review, a patch. If you would rather support the author with money, here are the channels that work from your country.

## DonationAlerts

<https://www.donationalerts.com/r/bahooo>

Cards, faster payments and wallets there; the service itself is outside my control.

## Crypto wallets

| Network | Address |
|---|---|
| Ethereum (ERC-20 compatible) | `0x984fE5Bfe7B1573063E20fb3722ba9d4A7a67F04` |
| TON (bounceable, workchain 0) | `UQCHOWrPc1SF_1ZK8pvZP-L1j4mGXmN8JPYrM9GUxJRdOMcf` |
| Bitcoin (native SegWit, P2WPKH) | `bc1q4ln0y35utxhdtkf2qnrnu6e784yyct4n25eu5y` |

The Bitcoin address starts with `bc1q` — that is native SegWit, accepted by current exchanges and wallets. When sending, pick the Bitcoin network and the bech32 address format (`bc1…`) rather than `1…` or `3…`: the format sets the fee, and old clients simply reject this address.

Before sending, compare the first and last six characters with this file in `main` (`git log -1 --format=%H -- .github/wallets.md` shows when it last changed). The Ethereum address passes the EIP-55 checksum: keccak-256 over the lowercase string reproduces exactly this letter casing. The check ran inside the stand container with `Crypto.Hash.keccak` (pycryptodome), and both canonical keccak-256 vectors matched.

The Bitcoin address passes the BIP-173 bech32 checksum: the BCH polynomial evaluates to exactly 1 over the expanded human-readable part and the data, and the address decodes to witness version 0 with a 20-byte program, i.e. scriptPubKey `0014afe6f2469c59aed5d92a04c73e6b3e3d484c2eb3`. The check was validated against all fifteen segwit vectors in BIP-173 itself (the six valid ones reproduce their published scriptPubKey, the nine invalid ones are rejected) and independently against the reference Python implementation shipped with that BIP, whose re-encoding returns this exact string. The TON address passes crc16-xmodem over the 34-byte body (tag `c71f`), and its bounceable flag and workchain 0 match the label in the table.

Donations carry no obligations: access to courses, code and releases does not depend on them, and there is no private build.
